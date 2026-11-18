#!/usr/bin/env python3
"""Step 3: decide which candidates are safe as global Hex replacements.

A replacement fires on every occurrence with no context, so what matters is precision:
the share of occurrences of the heard form that are mishearings.

Rules (see docs/gate.md for the derivation):
  - any occurrence labelled "literal"          -> in-context only (a replacement would corrupt it)
  - rare form (not a dictionary word, or a multi-word phrase), errors >= --min-rare, no literal
                                               -> replace
  - common single word, no literal, lower bound p_l >= --target
                                               -> replace
  - otherwise                                  -> not enough evidence
p_l is the one-sided Clopper-Pearson lower bound; with no failures it is alpha**(1/n).
Occurrences are counted once per calendar day, because one dictation burst repeats a word.

Also proposes recognition hints: the "meant" side of every pair that reaches "replace" or
"in-context only" and looks like a name or term (contains a capital, digit or symbol).
"""
import argparse
import datetime as dt
import gzip
import math
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from hexpaths import WORDS, load_json, save_json  # noqa: E402

def dictionary():
    """Webster's 2nd (web2, public domain), the list macOS ships as /usr/share/dict/words.
    It's bundled so the gate decides the same way on every OS: without it every word would
    count as rare and pass on 2 days instead of 29."""
    with gzip.open(WORDS, "rt", encoding="utf-8") as f:
        return {w.strip().lower() for w in f}


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
    ap.add_argument("--min-rare", type=int, default=2)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    words = dictionary()
    cands = load_json(a.candidates)["candidates"]
    occ = load_json(a.labels)["occurrences"]

    unlabelled = [o["id"] for o in occ if o.get("label") not in ("error", "literal", "unclear")]
    if unlabelled:
        sys.exit(f"{len(unlabelled)} occurrences have no label, e.g. {unlabelled[:3]}. Label them first.")

    plan = {"replacements": [], "hints": [], "rows": []}
    for c in cands:
        if c.get("already_in_hex"):
            plan["rows"].append({**c, "decision": "already in Hex"})
            continue
        mine = [o for o in occ if o["heard"] == c["heard"] and o["meant"] == c["meant"]]
        by_day = {}
        for o in mine:
            day = dt.datetime.fromtimestamp((o["timestamp_ms"] or 0) / 1000).date().isoformat()
            by_day.setdefault(day, set()).add(o["label"])
        # a day is literal if anything that day was literal, else error if anything was an error
        days = {d: ("literal" if "literal" in ls else "error" if "error" in ls else "unclear")
                for d, ls in by_day.items()}
        n_err = sum(v == "error" for v in days.values())
        n_lit = sum(v == "literal" for v in days.values())
        n = n_err + n_lit
        tokens = c["heard"].split()
        rare = len(tokens) > 1 or tokens[0].lower() not in words
        p_l = lower_bound(n_err, n, a.alpha)

        if n_lit:
            decision = "in-context only"
        elif rare and n_err >= a.min_rare:
            decision = "replace"
        elif not rare and p_l >= a.target:
            decision = "replace"
        else:
            decision = "not enough evidence"

        row = {"heard": c["heard"], "meant": c["meant"], "notes": c["notes"], "occurrences": len(mine),
               "days_error": n_err, "days_literal": n_lit, "rare_form": rare,
               "p_lower": round(p_l, 3), "decision": decision}
        plan["rows"].append(row)
        if decision == "replace":
            plan["replacements"].append({"matched_phrase": c["heard"], "output": c["meant"]})
        if looks_like_term(c["meant"]) and (n_err >= 1 or c["notes"] >= 2):
            plan["hints"].append(c["meant"])

    plan["hints"] = sorted(set(plan["hints"]))
    plan["settings"] = {"alpha": a.alpha, "target": a.target, "min_rare": a.min_rare,
                        "clean_days_needed_for_common_word": math.ceil(math.log(a.alpha) / math.log(a.target))}
    save_json(a.out, plan, indent=1)

    print(f'{"heard":<22} {"meant":<22} {"err d":>5} {"lit d":>5} {"p_l":>6}  decision')
    for r in plan["rows"]:
        if r["decision"] == "already in Hex":
            print(f'{r["heard"]:<22} {r["meant"]:<22} {"":>5} {"":>5} {"":>6}  already in Hex')
            continue
        print(f'{r["heard"]:<22} {r["meant"]:<22} {r["days_error"]:>5} {r["days_literal"]:>5} {r["p_lower"]:>6}  {r["decision"]}')
    print(f'\nreplacements proposed: {len(plan["replacements"])}   hints proposed: {len(plan["hints"])}   -> {a.out}')


if __name__ == "__main__":
    main()
