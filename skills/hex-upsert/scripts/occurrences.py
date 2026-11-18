#!/usr/bin/env python3
"""Step 2: list every Hex history entry where a candidate's heard form appears.

Matches against raw_text (before Hex's own replacements run), with the same literal,
case-insensitive, whole-word rule Hex uses. Each history entry counts once per candidate.
Writes a labelling sheet: Claude fills "label" with error | literal | unclear.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from hexpaths import history_entries, load_json, phrase_regex, save_json  # noqa: E402

CONTEXT = 70


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("candidates")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    cands = load_json(a.candidates)["candidates"]
    hist = history_entries()
    rows = []
    for c in cands:
        if c.get("already_in_hex"):
            continue
        rx = phrase_regex(c["heard"])
        for e in hist:
            raw = e.get("raw_text") or ""
            # skip matches Hex already got right ("PyTorch" when the pair is pytorch -> PyTorch)
            m = next((m for m in rx.finditer(raw) if m.group(0) != c["meant"]), None)
            if not m:
                continue
            lo, hi = max(0, m.start() - CONTEXT), min(len(raw), m.end() + CONTEXT)
            rows.append({
                "id": f'{c["heard"]}|{e["id"]}',
                "heard": c["heard"],
                "meant": c["meant"],
                "entry": e["id"],
                "timestamp_ms": e.get("timestamp_ms"),
                "context": raw[lo:m.start()] + "⟦" + m.group(0) + "⟧" + raw[m.end():hi],
                "label": None,
            })
    save_json(a.out, {"history_entries": len(hist), "occurrences": rows}, indent=1)
    print(f"{len(rows)} occurrences across {len(hist)} history entries -> {a.out}")


if __name__ == "__main__":
    main()
