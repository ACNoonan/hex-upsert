#!/usr/bin/env python3
"""Step 1: nominate candidate (heard -> meant) pairs.

Sources, in order of trust:
  1. tags Claude writes in its replies:  [heard: "X" → meant: "Y"]
  2. --seed FILE: a JSON list of {"heard", "meant"} you add by hand

Pairs already present as Hex replacements are marked so the report can skip them.
Writes JSON to stdout (or --out).  Read-only on every input.
"""
import argparse
import glob
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from hexpaths import LOGS_DIR, SETTINGS, load_json  # noqa: E402

TAG = re.compile(r'\[heard:\s*["“](?P<heard>[^"”\]]{1,80})["”]\s*(?:→|->)\s*meant:\s*["“](?P<meant>[^"”\]]{1,80})["”]\s*\]')


def assistant_texts(path):
    with open(path, errors="replace") as f:
        for line in f:
            if '"assistant"' not in line or "heard:" not in line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("type") != "assistant":
                continue
            content = (obj.get("message") or {}).get("content") or []
            for block in content if isinstance(content, list) else []:
                if isinstance(block, dict) and block.get("type") == "text":
                    yield obj.get("timestamp"), block.get("text", "")


def is_placeholder(heard, meant):
    """Skip the tag format quoted as an example: ("X", "Y"), "<exact words ...>", "...".
    Real mishearings of a single letter are not worth a global replacement anyway."""
    return any(len(s.strip()) <= 1 or "<" in s or s.strip() in ("...", "…") for s in (heard, meant))


def existing_replacements():
    if not os.path.exists(SETTINGS):
        return {}
    dp = load_json(SETTINGS).get("dictation_processing", {})
    out = {}
    for mode in [dp.get("default_mode", {})] + dp.get("modes", []):
        for r in mode.get("replacements", []):
            out[r["matched_phrase"].strip().lower()] = r["output"]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=float, default=60, help="only read logs modified in the last N days")
    ap.add_argument("--seed", help="JSON list of {heard, meant} to add by hand")
    ap.add_argument("--out")
    a = ap.parse_args()

    cutoff = time.time() - a.days * 86400
    pairs = {}

    def add(heard, meant, source):
        key = (heard.strip().lower(), meant.strip())
        p = pairs.setdefault(key, {"heard": heard.strip(), "meant": meant.strip(), "sources": []})
        p["sources"].append(source)

    files = [f for f in glob.glob(os.path.join(LOGS_DIR, "*", "*.jsonl")) if os.path.getmtime(f) >= cutoff]
    for path in files:
        for ts, text in assistant_texts(path):
            for m in TAG.finditer(text):
                add(m["heard"], m["meant"], {"kind": "tag", "session": os.path.basename(path), "ts": ts})

    if a.seed:
        for row in load_json(a.seed):
            add(row["heard"], row["meant"], {"kind": "seed"})

    have = existing_replacements()
    out = []
    for p in pairs.values():
        if p["heard"] == p["meant"] or is_placeholder(p["heard"], p["meant"]):
            continue
        p["notes"] = len(p["sources"])
        p["already_in_hex"] = have.get(p["heard"].lower()) == p["meant"]
        out.append(p)
    out.sort(key=lambda p: -p["notes"])

    result = {"logs_scanned": len(files), "candidates": out}
    text = json.dumps(result, indent=1, ensure_ascii=False)
    if a.out:
        open(a.out, "w").write(text)
    else:
        print(text)


if __name__ == "__main__":
    main()
