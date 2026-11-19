#!/usr/bin/env python3
"""Step 3: decide which candidates are safe as global Hex replacements.

A replacement fires on every occurrence with no context, so what matters is precision: the
share of occurrences of the heard form that are mishearings. Two things decide it. Can the
heard form be said on purpose? Does that sound always mean the same target? The gate answers
both by sorting each pair into a type (see classify, and docs/gate.md for the reasoning):

  non-word        the heard form isn't an ordinary word       Superbase -> Supabase
  term-as-words   a term came out as ordinary words           clawed code -> Claude Code
  written-form    right words, wrong case or spacing          spit -> SPIT
  word-swap       an ordinary word for an ordinary word       air -> error
  dropped-word    words added, dropped or cut off             don't -> do

and each type has one of three evidence rules:

  term   (non-word; term-as-words and written-form when the heard form is a phrase)
         no literal day, at least 1 error day of its own, and --min-rare error days across
         every heard form of the same target ("Verselle" and "verse cell" both count for Vercel).
         A heard form shares days only if it is spelled like the target; "relu" -> "Locke"
         isn't, so it needs --min-rare days of its own.
  bound  (word-swap; term-as-words and written-form when the heard form is one ordinary word)
         no literal day, and the lower bound p_l on precision reaches --target
  never  (dropped-word) nothing is being substituted, so it stays a correction made in context

Any occurrence labelled "literal" means in-context only, whatever the type.
p_l is the one-sided Clopper-Pearson lower bound; with no failures it is alpha**(1/n).
Occurrences are counted once per calendar day, because one dictation burst repeats a word.

"Ordinary" means the word is said at least --ordinary-per-million times per million words in
the bundled subtitle frequency list (data/words.txt.gz, see data/NOTICE.md).

Also proposes vocabulary, per target term rather than per pair: every non-word or
term-as-words target that looks like a name or term, with the heard forms that are safe to
give Hex as "sounds like" spellings.
"""
import argparse
import datetime as dt
import gzip
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
from hexpaths import WORDS, load_json, save_json  # noqa: E402

TERM, BOUND, NEVER = "term", "bound", "never"
SUFFIXES = ("n't", "'re", "'ve", "'ll", "'s", "'d", "'m", "ies", "ing", "es", "ed", "s", "d")
NEGATIONS = ("n't", "not", "never", "no")


def dictionary(per_million=1.0):
    """The words people ordinarily say: at least `per_million` uses per million words of
    subtitles. Bundled so the gate decides the same way on every OS."""
    counts = {}
    with gzip.open(WORDS, "rt", encoding="utf-8") as f:
        for line in f:
            word, _, n = line.partition(" ")
            counts[word] = int(n)
    floor = per_million * sum(counts.values()) / 1e6
    return {w for w, n in counts.items() if n >= floor}


def clean(token):
    return token.lower().replace("’", "'").strip(".,;:!?\"()")


def known(token, words):
    """An ordinary word: in the list as it stands, or once a contraction or a regular ending
    is removed (the list splits "don't" and lacks rarer inflections). A number is ordinary."""
    t = clean(token)
    if not t or t in words or not any(ch.isalpha() for ch in t):
        return True
    if "-" in t:  # 'non-signed-in' is ordinary if each part is
        return all(known(part, words) for part in t.split("-"))
    for suf in SUFFIXES:
        if t.endswith(suf) and len(t) > len(suf) + 1:
            stem = t[: -len(suf)]
            if stem in words or stem + "e" in words or (suf == "ies" and stem + "y" in words):
                return True
    return False


def squash(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def cores(heard, meant):
    """The words that differ, once the words both sides share at the start and end are set
    aside: 'free our non-signed-in users' -> 'free or non-signed-in users' is our -> or."""
    h, m = heard.split(), meant.split()
    a = 0
    while a < min(len(h), len(m)) and squash(h[a]) == squash(m[a]):
        a += 1
    b = 0
    while b < min(len(h), len(m)) - a and squash(h[-1 - b]) == squash(m[-1 - b]):
        b += 1
    return h[a:len(h) - b], m[a:len(m) - b], a


def is_term(heard, meant, words, m_core=None, offset=0):
    """The correction names something: it has a word that isn't ordinary ('PyTorch'), or a
    capital the heard form didn't have ('clawed code' -> 'Claude Code'). When a phrase starts
    with a capital on both sides, that capital is only the start of a sentence."""
    h, m = heard.split(), meant.split()
    m_core = m if m_core is None else m_core
    for i, t in enumerate(m_core):
        if not known(t, words):
            return True
        sentence_start = offset + i == 0 and len(m) > 1 and h[0][:1].isupper()
        if any(ch.isupper() for ch in t) and t != "I" and not sentence_start:
            return True
    return False


def cut_or_negated(a, b):
    """One word is the other cut short ('his' for 'history') or negated ('do' for 'don't')."""
    a, b = sorted((clean(a), clean(b)), key=len)
    if b.startswith(a) and len(b) - len(a) >= 2:
        return True
    return any(b == a + n or b == a + " " + n for n in NEGATIONS)


def spelled_alike(h_core, target, floor=0.5):
    """The heard form looks like a spelling of the target, so it can share the target's
    evidence: 'Verselle' and 'verse cell' for Vercel, not 'relu' for Locke."""
    a, b = squash(" ".join(h_core)), squash(target)
    if not a or not b:
        return False
    row = list(range(len(b) + 1))  # edit distance, one row at a time
    for i, ca in enumerate(a, 1):
        prev, row[0] = row[0], i
        for j, cb in enumerate(b, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (ca != cb))
    return 1 - row[-1] / max(len(a), len(b)) >= floor


def classify(heard, meant, words):
    """(type, evidence rule, target). See the module docstring for the types."""
    h_core, m_core, offset = cores(heard, meant)
    phrase = len(heard.split()) > 1
    if squash(heard) == squash(meant):  # same letters: only case, spacing or punctuation moved
        return "written-form", TERM if phrase else BOUND, meant
    target = " ".join(m_core)
    if not h_core or not m_core:
        return "dropped-word", NEVER, target or meant
    h_ordinary = all(known(t, words) for t in h_core)
    term = is_term(heard, meant, words, m_core, offset)
    if h_ordinary and not term and len(h_core) == 1 and len(m_core) == 1 and cut_or_negated(h_core[0], m_core[0]):
        return "dropped-word", NEVER, target
    if not h_ordinary:
        return "non-word", TERM, target
    if term:
        return "term-as-words", TERM if phrase else BOUND, target
    return "word-swap", BOUND, target


def binom_sf(k, n, p):
    """P(X >= k) for X ~ Binomial(n, p)."""
    return sum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k, n + 1))


def lower_bound(k, n, alpha):
    """One-sided Clopper-Pearson lower bound on p given k successes in n."""
    if n == 0 or k == 0:
        return 0.0
    if k == n:
        return alpha ** (1 / n)
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if binom_sf(k, n, mid) < alpha:
            lo = mid
        else:
            hi = mid
    return lo


def looks_like_term(s):
    """A name or term worth priming the model with: 'Supabase', 'Qwen3.8-27B', 'Nomad List'.
    Not a phrase ('open in Cursor'), not a path."""
    toks = s.split()
    if not toks or len(toks) > 3 or "/" in s or "~" in s:
        return False
    return any(ch.isupper() for ch in toks[0])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("candidates")
    ap.add_argument("labels")
    ap.add_argument("--alpha", type=float, default=0.05)
    ap.add_argument("--target", type=float, default=0.9)
    ap.add_argument("--min-rare", type=int, default=2, help="error days a target needs under the term rule")
    ap.add_argument("--ordinary-per-million", type=float, default=1.0)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    words = dictionary(a.ordinary_per_million)
    cands = load_json(a.candidates)["candidates"]
    occ = load_json(a.labels)["occurrences"]

    unlabelled = [o["id"] for o in occ if o.get("label") not in ("error", "literal", "unclear")]
    if unlabelled:
        sys.exit(f"{len(unlabelled)} occurrences have no label, e.g. {unlabelled[:3]}. Label them first.")

    plan = {"replacements": [], "hints": [], "vocabulary": [], "rows": []}
    rows, targets = [], {}
    for c in cands:
        if c.get("already_in_hex"):
            plan["rows"].append({**c, "decision": "already in Hex"})
            continue
        kind, rule, target = classify(c["heard"], c["meant"], words)
        mine = [o for o in occ if o["heard"] == c["heard"] and o["meant"] == c["meant"]]
        by_day = {}
        for o in mine:
            day = dt.datetime.fromtimestamp((o["timestamp_ms"] or 0) / 1000).date().isoformat()
            by_day.setdefault(day, set()).add(o["label"])
        # a day is literal if anything that day was literal, else error if anything was an error
        days = {d: ("literal" if "literal" in ls else "error" if "error" in ls else "unclear")
                for d, ls in by_day.items()}
        err_days = {d for d, v in days.items() if v == "error"}
        n_lit = sum(v == "literal" for v in days.values())
        h_core = cores(c["heard"], c["meant"])[0] or c["heard"].split()
        row = {"heard": c["heard"], "meant": c["meant"], "notes": c["notes"], "occurrences": len(mine),
               "type": kind, "evidence": rule, "target": target,
               "days_error": len(err_days), "days_literal": n_lit,
               "p_lower": round(lower_bound(len(err_days), len(err_days) + n_lit, a.alpha), 3)}
        row["pooled"] = rule == TERM and spelled_alike(h_core, target)
        rows.append((row, err_days, h_core))
        t = targets.setdefault(squash(target), {"term": target, "days": set(), "notes": 0, "rows": []})
        if row["pooled"]:
            t["days"] |= err_days
        t["notes"] += c["notes"]
        t["rows"].append((row, h_core))

    for row, err_days, _ in rows:
        t = targets[squash(row["target"])]
        row["target_days"] = len(t["days"]) if row.pop("pooled") else len(err_days)
        if row["days_literal"]:
            decision = "in-context only"
        elif row["evidence"] == NEVER:
            decision = "in-context only"
        elif row["evidence"] == TERM and err_days and row["target_days"] >= a.min_rare:
            decision = "replace"
        elif row["evidence"] == BOUND and row["p_lower"] >= a.target:
            decision = "replace"
        else:
            decision = "not enough evidence"
        row["decision"] = decision
        plan["rows"].append(row)
        if decision == "replace":
            plan["replacements"].append({"matched_phrase": row["heard"], "output": row["meant"]})

    # vocabulary: one entry per target term. A "sounds like" spelling is something Hex may
    # show instead of the term, so only heard forms nobody says on purpose go in.
    for t in targets.values():
        mine = [(r, h) for r, h in t["rows"] if r["type"] in ("non-word", "term-as-words")]
        if not mine or not looks_like_term(t["term"]) or not (any(r["days_error"] for r, _ in mine) or t["notes"] >= 2):
            continue
        spellings = sorted({" ".join(h) for r, h in mine
                            if not r["days_literal"] and (len(h) > 1 or not known(h[0], words))})
        plan["vocabulary"].append({"term": t["term"], "sounds_like": spellings,
                                   "days_error": max(len(t["days"]), max(r["days_error"] for r, _ in mine)),
                                   "heard_forms": len(t["rows"])})
    plan["vocabulary"].sort(key=lambda v: v["term"].lower())
    plan["hints"] = [v["term"] for v in plan["vocabulary"]]
    plan["settings"] = {"alpha": a.alpha, "target": a.target, "min_rare": a.min_rare,
                        "ordinary_per_million": a.ordinary_per_million,
                        "clean_days_needed_for_common_word": math.ceil(math.log(a.alpha) / math.log(a.target))}
    save_json(a.out, plan, indent=1)

    if plan["vocabulary"]:
        print("vocabulary (teach Hex the term; fixes every heard form at once)")
        for v in plan["vocabulary"]:
            extra = f'  sounds like: {", ".join(v["sounds_like"])}' if v["sounds_like"] else ""
            print(f'  {v["term"]:<22} {v["days_error"]} error day(s) across {v["heard_forms"]} heard form(s){extra}')
        print()
    print(f'{"heard":<22} {"meant":<22} {"type":<14} {"err d":>5} {"tgt d":>5} {"lit d":>5} {"p_l":>6}  decision')
    for r in plan["rows"]:
        if r["decision"] == "already in Hex":
            print(f'{r["heard"][:22]:<22} {r["meant"][:22]:<22} {"":<14} {"":>5} {"":>5} {"":>5} {"":>6}  already in Hex')
            continue
        print(f'{r["heard"][:22]:<22} {r["meant"][:22]:<22} {r["type"]:<14} {r["days_error"]:>5} {r["target_days"]:>5} '
              f'{r["days_literal"]:>5} {r["p_lower"]:>6}  {r["decision"]}')
    print(f'\nreplacements proposed: {len(plan["replacements"])}   vocabulary proposed: {len(plan["vocabulary"])}   -> {a.out}')


if __name__ == "__main__":
    main()
