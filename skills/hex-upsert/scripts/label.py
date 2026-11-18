#!/usr/bin/env python3
"""Step 3, unattended: label every occurrence with headless Claude Code.

Runs `claude -p` on the user's Claude subscription with every API key stripped from the
environment, so it can never fall back to a billed key. No tools, no session persistence.
Fills "label" in the labels sheet in place. Exits non-zero if any label is missing.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))
from hexpaths import load_json, save_json  # noqa: E402

CLAUDE = os.environ.get("CLAUDE_BIN") or shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")

SYSTEM = """You label speech-to-text output. Each item shows a snippet of dictated text with one
phrase marked like ⟦this⟧, plus a candidate correction. Decide what the speaker meant by the
marked phrase:
- "error": the speaker meant the candidate correction, and the marked phrase is a mishearing
- "literal": the speaker meant the marked words themselves
- "unclear": the snippet doesn't let you tell
Read each snippet on its own. Don't assume all items for a phrase share a label.
Answer with only a JSON object mapping each item id to its label, nothing else."""


def ask(items, model, env):
    r = subprocess.run(
        [CLAUDE, "-p", json.dumps(items, ensure_ascii=False), "--tools", "", "--model", model,
         "--no-session-persistence", "--system-prompt", SYSTEM],
        capture_output=True, text=True, encoding="utf-8", env=env, timeout=600,
    )
    if r.returncode != 0:
        sys.exit(f"claude -p failed ({r.returncode}): {r.stderr[-500:]}")
    m = re.search(r"\{.*\}", r.stdout, re.S)
    if not m:
        sys.exit(f"no JSON in claude output: {r.stdout[:300]}")
    return json.loads(m.group(0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("labels")
    ap.add_argument("--model", default="opus")
    ap.add_argument("--passes", type=int, default=2, help="independent passes; disagreement -> unclear")
    a = ap.parse_args()

    sheet = load_json(a.labels)
    todo = [o for o in sheet["occurrences"] if o.get("label") is None]
    if not todo:
        print("nothing to label")
        return
    items = [{"id": o["id"], "snippet": o["context"], "candidate_correction": o["meant"]} for o in todo]
    # strip anything that could bill an API account; CLAUDE_CODE_OAUTH_TOKEN (claude setup-token) is a
    # subscription login, so it stays
    env = {k: v for k, v in os.environ.items()
           if not re.search(r"API_KEY|AUTH_TOKEN", k) or k == "CLAUDE_CODE_OAUTH_TOKEN"}
    runs = [ask(items, a.model, env) for _ in range(a.passes)]
    flips = 0
    for o in todo:
        votes = {r.get(o["id"]) for r in runs}
        if len(votes) == 1 and next(iter(votes)) in ("error", "literal", "unclear"):
            o["label"] = next(iter(votes))
        elif votes <= {"error", "literal", "unclear"}:
            o["label"] = "unclear"
            flips += 1
        else:
            o["label"] = None
    print(f"passes disagreed on {flips} of {len(todo)} (labelled unclear)")
    save_json(a.labels, sheet, indent=1)
    missing = [o["id"] for o in todo if o["label"] is None]
    print(f"labelled {len(todo) - len(missing)} of {len(todo)}")
    if missing:
        sys.exit(f"missing labels: {missing[:5]}")


if __name__ == "__main__":
    main()
