#!/usr/bin/env python3
"""First-run scan: find words in Hex's history that aren't ordinary words.

Tags only exist from the day the plugin is installed, so a new user has no candidates. But the
most reliable kind of mishearing, a term Hex spelled as a non-word ("Superbase", "Florinopolis"),
is already sitting in Hex's history. This lists every such form with a few snippets. Claude reads
them and decides which are mishearings (and of what) and which are real terms Hex got right
("GitHub"). The mishearings go into a seed file for collect.py --seed.

Skips every word in the bundled frequency list (a wider net than the gate's "ordinary", which
would flag rare real words), acronyms in capitals, and anything Hex already replaces or holds
in its vocabulary. Read-only.
"""
import argparse
import datetime as dt
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
from gate import dictionary, known  # noqa: E402
from hexpaths import SETTINGS, history_entries, load_json, save_json  # noqa: E402

WORD = re.compile(r"[^\W\d_](?:[\w'’-]*[^\W_])?")
CONTEXT = 60


def already_handled():
    """Lowercased forms Hex already rewrites or knows: replacement phrases, vocabulary terms
    and their "sounds like" spellings."""
    try:
        s = load_json(SETTINGS)
    except (OSError, ValueError):
        return set()
    out = set()
    dp = s.get("dictation_processing") or {}
    for mode in [dp.get("default_mode") or {}] + (dp.get("modes") or []):
        for r in mode.get("replacements", []):
            out.update(r.get("matched_phrase", "").lower().split())
            out.update(r.get("output", "").lower().split())
    for v in s.get("vocabulary") or []:
        v = {"term": v} if isinstance(v, str) else v
        for form in [v.get("term", "")] + list(v.get("sounds_like") or []):
            out.update(form.lower().split())
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=40, help="show at most this many forms")
    ap.add_argument("--acronyms", action="store_true", help="include words in capitals (MCP, GPU)")
    a = ap.parse_args()

    words, skip = dictionary(per_million=0), already_handled()  # any of the 50,000 listed words is a real word
    hist = history_entries()
    found = {}
    for e in hist:
        raw = e.get("raw_text") or ""
        day = dt.datetime.fromtimestamp((e.get("timestamp_ms") or 0) / 1000).date().isoformat()
        for m in WORD.finditer(raw):
            w = m.group(0)
            if len(w) < 3 or known(w, words) or w.lower() in skip or (w.isupper() and not a.acronyms):
                continue
            f = found.setdefault(w.lower(), {"form": w, "count": 0, "days": set(), "contexts": []})
            f["count"] += 1
            f["days"].add(day)
            if len(f["contexts"]) < 3:
                lo, hi = max(0, m.start() - CONTEXT), min(len(raw), m.end() + CONTEXT)
                f["contexts"].append(raw[lo:m.start()] + "⟦" + w + "⟧" + raw[m.end():hi])
    rows = sorted(found.values(), key=lambda f: (-len(f["days"]), -f["count"], f["form"].lower()))
    for f in rows:
        f["days"] = len(f["days"])
    save_json(a.out, {"history_entries": len(hist), "unknown_forms": len(rows), "forms": rows[:a.limit]}, indent=1)
    print(f"{len(rows)} forms that aren't ordinary words, in {len(hist)} history entries. Top {min(a.limit, len(rows))}:")
    for f in rows[:a.limit]:
        print(f'  {f["form"]:<24} {f["count"]:>3} uses on {f["days"]} day(s)')
    print(f"-> {a.out}")


if __name__ == "__main__":
    main()
