#!/usr/bin/env python3
"""SessionStart hook for the hex-upsert plugin. Whatever it prints goes into Claude's context.

1. The tag rule. Claude only writes [heard: "X" → meant: "Y"] tags if told to, so this adds
   the rule to every session. The rule has a version. It's skipped only if ~/.claude/CLAUDE.md
   carries the marker for this version ("hex-upsert-rule: v2"), so a copy of an older rule in
   CLAUDE.md never holds a session on the old wording.
2. A weekly nudge, on fresh startups only. Once every 7 days it runs the cheap, read-only steps
   (collect + occurrences, about 2 s) and tells Claude to offer /hex-upsert when some pair has
   unreviewed occurrences and shows up on 2+ days in total, the least any replacement needs.
   If the weekly schedule is installed it only reports a plan the schedule saved.

Never writes Hex settings, never calls a model, and never fails the session: any error is silent.
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from hexpaths import STATE, hex_installed, load_json, read_text, write_text  # noqa: E402

WEEK = 7 * 86400
PLIST = os.path.expanduser("~/Library/LaunchAgents/local.hex-upsert.plist")


def scheduled():
    """The weekly job is installed: schedule.sh writes <state>/scheduled; older installs only have the plist."""
    return os.path.exists(os.path.join(STATE, "scheduled")) or os.path.exists(PLIST)

RULE_VERSION = "v2"
MARKER = f"hex-upsert-rule: {RULE_VERSION}"
SUPERSEDES = " This rule replaces any older instruction about [heard: …] tags."

RULE = """hex-upsert: the user dictates through Hex, a local speech-to-text app, so a prompt can contain words Hex misheard. Read for the intended meaning as you normally would. Separately, a few of those mishearings are worth teaching to Hex, and you nominate one by writing the tag [heard: "<exact words in the prompt>" → meant: "<intended words>"]. The hex-upsert skill mines these tags into Hex replacements, and a Hex replacement is a find-and-replace with no context: it rewrites the heard words in every future transcript. So the test for a tag is whether the user would want "heard" turned into "meant" every time they say those words, in any sentence. That is usually a specific term Hex doesn't know (a name, a product, a library, an acronym, a piece of jargon) that came out as sound-alike words, such as "pie torch" for PyTorch or "verse cell" for Vercel. Most corrections fail the test and get no tag, even though you still make them and say what you assumed: a dropped, added or swapped ordinary word ("don't" for "do", "his" for "history", "our" for "or"), a negation or grammar slip, an ordinary word misheard as another ordinary word once, a typed typo, and anything you worked out from what this sentence must mean. Tag only the misheard term itself and leave the words around it out of the tag. Write a tag once per pair per turn. If you're unsure, don't write one."""


def has_rule():
    p = os.path.join(os.path.expanduser("~"), ".claude", "CLAUDE.md")
    try:
        return MARKER in read_text(p)
    except OSError:
        return False


def day(ms):
    return time.strftime("%Y-%m-%d", time.localtime((ms or 0) / 1000))


def nudge():
    pending = os.path.join(STATE, "pending.json")
    if scheduled():
        if os.path.exists(pending):
            n = len(load_json(pending).get("replacements", []))
            return (f"hex-upsert: the weekly run found {n} Hex correction(s) that passed the safety gate "
                    "and is waiting for a yes. At a natural pause, mention it in one line and offer to run the hex-upsert skill. "
                    "Don't interrupt the user's task.")
        return None

    stamp = os.path.join(STATE, "last_check")
    try:
        if time.time() - float(read_text(stamp)) < WEEK:
            return None
    except (OSError, ValueError):
        pass
    work = os.path.join(STATE, "check")
    os.makedirs(work, exist_ok=True)
    write_text(stamp, str(int(time.time())))
    cand, occ = os.path.join(work, "candidates.json"), os.path.join(work, "occurrences.json")
    for args in (["collect.py", "--days", "60", "--out", cand], ["occurrences.py", cand, "--out", occ]):
        subprocess.run([sys.executable, os.path.join(HERE, args[0]), *args[1:]],
                       capture_output=True, check=True, timeout=60)

    try:
        reviewed = set(load_json(os.path.join(STATE, "reviewed.json")))
    except (OSError, ValueError):
        reviewed = set()
    by_pair = {}
    for o in load_json(occ)["occurrences"]:
        p = by_pair.setdefault((o["heard"], o["meant"]), {"days": set(), "new": 0})
        p["days"].add(day(o.get("timestamp_ms")))
        p["new"] += o["id"] not in reviewed
    ready = [k for k, p in by_pair.items() if p["new"] and len(p["days"]) >= 2]
    if not ready:
        return None
    names = ", ".join(f'"{h}" → "{m}"' for h, m in ready[:5]) + (" …" if len(ready) > 5 else "")
    return (f"hex-upsert: {len(ready)} misheard pair(s) have new evidence in Hex's history since the last review "
            f"({names}). At a natural pause, mention it in one line and offer to run the hex-upsert skill. "
            "Don't interrupt the user's task.")


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        event = {}
    if not hex_installed():  # no Hex on this machine: stay silent
        return
    out = []
    if not has_rule():
        out.append(RULE + SUPERSEDES)
    if event.get("source", "startup") == "startup":
        try:
            msg = nudge()
            if msg:
                out.append(msg)
        except Exception:  # noqa: BLE001  a hook must never break the session
            pass
    if out:
        print("\n\n".join(out))


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001
        pass
