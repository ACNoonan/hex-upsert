#!/usr/bin/env python3
"""What the replacements are doing, week by week. Read-only, aggregate counts only.

For each ISO week it prints:
  dictations   entries in Hex's history
  fixed        times a replacement fired: the misheard form is in raw_text and the corrected
               form is in final_text, so the mishearing never reached Claude
  missed       times a misheard form that now has a replacement went through unchanged
               (before the replacement existed, or in a mode that doesn't use it)
  tags         mishearings Claude still had to correct and tag, from the session logs
  repeat tags  tags for a pair Claude had already tagged in an earlier session

A replacement is working when "missed" and "repeat tags" fall to zero after it's added.
"""
import argparse
import datetime as dt
import glob
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from collect import TAG, assistant_texts, existing_replacements, is_placeholder  # noqa: E402
from hexpaths import LOGS_DIR, history_entries, phrase_regex  # noqa: E402


def week(d):
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=float, default=60)
    a = ap.parse_args()
    rows = {}

    def row(w):
        return rows.setdefault(w, {"dictations": 0, "fixed": 0, "missed": 0, "tags": 0, "repeat": 0})

    reps = [(phrase_regex(h), out) for h, out in existing_replacements().items()]
    for e in history_entries():
        raw, final = e.get("raw_text") or "", e.get("final_text") or ""
        r = row(week(dt.datetime.fromtimestamp((e.get("timestamp_ms") or 0) / 1000).date()))
        r["dictations"] += 1
        for rx, out in reps:
            n = sum(1 for m in rx.finditer(raw) if m.group(0) != out)
            if n:
                r["fixed" if out in final and not any(m.group(0) != out for m in rx.finditer(final)) else "missed"] += n

    cutoff, tagged = time.time() - a.days * 86400, []
    for path in glob.glob(os.path.join(LOGS_DIR, "*", "*.jsonl")):
        if os.path.getmtime(path) < cutoff:
            continue
        for ts, text in assistant_texts(path):
            for m in TAG.finditer(text):
                if ts and not is_placeholder(m["heard"], m["meant"]):
                    tagged.append((ts, path, (m["heard"].strip().lower(), m["meant"].strip())))
    first = {}
    for ts, path, pair in sorted(tagged):
        r = row(week(dt.date.fromisoformat(ts[:10])))
        r["tags"] += 1
        if first.setdefault(pair, path) != path:
            r["repeat"] += 1

    print(f'{"week":<9} {"dictations":>10} {"fixed":>6} {"missed":>7} {"tags":>5} {"repeat tags":>12}')
    for w in sorted(rows):
        r = rows[w]
        print(f'{w:<9} {r["dictations"]:>10} {r["fixed"]:>6} {r["missed"]:>7} {r["tags"]:>5} {r["repeat"]:>12}')
    print(f"\n{len(reps)} replacement(s) in Hex")


if __name__ == "__main__":
    main()
