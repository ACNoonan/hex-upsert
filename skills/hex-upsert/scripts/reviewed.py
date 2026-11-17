#!/usr/bin/env python3
"""Record which occurrences the user has reviewed, so the weekly nudge only fires on new evidence.

  reviewed.py LABELS.json        add every labelled occurrence id to the reviewed set
  reviewed.py --clear-pending    drop the plan a notify-only scheduled run saved
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from hexpaths import STATE, load_json  # noqa: E402


def main():
    os.makedirs(STATE, exist_ok=True)
    if sys.argv[1:] == ["--clear-pending"]:
        p = os.path.join(STATE, "pending.json")
        if os.path.exists(p):
            os.remove(p)
        print("cleared pending plan")
        return
    path = os.path.join(STATE, "reviewed.json")
    try:
        seen = set(load_json(path))
    except (OSError, ValueError):
        seen = set()
    before = len(seen)
    seen |= {o["id"] for o in load_json(sys.argv[1])["occurrences"] if o.get("label")}
    json.dump(sorted(seen), open(path, "w"), indent=0, ensure_ascii=False)
    print(f"reviewed set: {before} -> {len(seen)}")


if __name__ == "__main__":
    main()
