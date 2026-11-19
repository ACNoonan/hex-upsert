#!/usr/bin/env python3
"""Does the tag rule make Claude tag the right things? Not part of CI: it calls Claude.

Each prompt in tag_rule_cases.json is synthetic dictation with a known answer: "tag" (a term
Hex misheard), "none" (an ordinary-word garble, a dropped word, a typo or a clean prompt) or
"either". Each runs through headless Claude Code with the rule appended to the system prompt,
isolated from your ~/.claude (no CLAUDE.md, hooks or plugins), and the reply is checked for a
[heard: …] tag.

  python3 tests/tag_rule_eval.py                 the current rule, once per case
  python3 tests/tag_rule_eval.py --reps 3        three runs per case
  python3 tests/tag_rule_eval.py --rule v1       the first rule, to compare
  python3 tests/tag_rule_eval.py --out FILE      also save every reply as JSON

It runs on your Claude subscription. API keys are stripped from the environment, as in label.py.
"""
import argparse
import concurrent.futures as cf
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "skills", "hex-upsert", "scripts"))
from collect import TAG  # noqa: E402
from session_start import RULE  # noqa: E402

RULES = {
    "current": RULE,
    "v1": 'hex-upsert: the user dictates through Hex, a local speech-to-text app. When you fix a word or phrase in '
          'their prompt that Hex misheard, write the tag [heard: "<exact words in the prompt>" → meant: "<intended '
          'words>"] once per pair per turn. Use it only for sound-alike mishearings. Typos and your reading of what '
          "they meant don't get the tag. The hex-upsert skill mines these tags into Hex replacements.",
}


def ask(rule, prompt, cwd):
    env = {k: v for k, v in os.environ.items()
           if not re.search(r"API_KEY|AUTH_TOKEN", k) or k == "CLAUDE_CODE_OAUTH_TOKEN"}
    try:
        r = subprocess.run(
            ["claude", "-p", prompt, "--tools", "", "--setting-sources", "project", "--strict-mcp-config",
             "--disable-slash-commands", "--no-session-persistence", "--append-system-prompt", rule],
            capture_output=True, text=True, encoding="utf-8", env=env, timeout=120, cwd=cwd)
    except (subprocess.TimeoutExpired, OSError):  # one hung call must not lose the run
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rule", choices=sorted(RULES), default="current")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--out")
    a = ap.parse_args()
    with open(os.path.join(HERE, "tag_rule_cases.json"), encoding="utf-8") as f:
        cases = json.load(f)
    cwd = tempfile.mkdtemp(prefix="hexup-eval-")  # an empty folder: no project settings or CLAUDE.md
    runs = []
    with cf.ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(ask, RULES[a.rule], c["prompt"], cwd): c for c in cases for _ in range(a.reps)}
        for f in cf.as_completed(futs):
            c, text = futs[f], f.result()
            runs.append({"id": c["id"], "want": c["want"], "reply": text,
                         "tags": TAG.findall(text) if text else []})
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(runs, f, indent=1, ensure_ascii=False)

    failed = sum(r["reply"] is None for r in runs)
    for c in cases:
        mine = [r for r in runs if r["id"] == c["id"] and r["reply"] is not None]
        n = sum(bool(r["tags"]) for r in mine)
        ok = c["want"] == "either" or n == (len(mine) if c["want"] == "tag" else 0)
        tags = sorted({f"{h} → {m}" for r in mine for h, m in r["tags"]})
        print(f'{"ok  " if ok else "MISS"} {c["id"]:<15} want={c["want"]:<6} tagged {n}/{len(mine)}  {"; ".join(tags)}')
    print(f"\nrule: {a.rule}")
    for want, label in (("tag", "terms tagged"), ("none", "non-terms tagged (should be 0)")):
        mine = [r for r in runs if r["want"] == want and r["reply"] is not None]
        print(f'{label}: {sum(bool(r["tags"]) for r in mine)}/{len(mine)}')
    if failed:
        print(f"{failed} call(s) failed and are left out")


if __name__ == "__main__":
    main()
