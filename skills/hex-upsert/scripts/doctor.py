#!/usr/bin/env python3
"""Setup check: is everything in place for hex-upsert to find and apply corrections?

  doctor.py          report each check as ok / fix / note
  doctor.py --fix    also set Hex's history retention to a month and turn vocabulary help on
                     (Hex 3 only; both go through Hex's own CLI)

Checks: Hex and its version, how much history Hex keeps and has, whether vocabulary affects
transcription, whether Claude is being told to tag mishearings and has written any tags, the
`claude` command (the weekly job needs it), and the weekly job. Changes nothing without --fix.
"""
import argparse
import glob
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from collect import TAG, assistant_texts, is_placeholder  # noqa: E402
from hexpaths import (BACKEND, HEX_DIR, LOGS_DIR, SETTINGS, STATE, HexError, hex_call, hex_cli,  # noqa: E402
                      hex_installed, history_entries, load_json, read_text)
from session_start import MARKER, scheduled  # noqa: E402

SHORT = ("off", "day", "week")
rows = []


def say(status, what, detail):
    rows.append(status)
    print(f"{status:<5} {what:<20} {detail}")


def cli(*args):
    """Run a `hex` command that has no --json form (labs, --version). Returns its output."""
    path = hex_cli()
    if not path:
        raise HexError("no-cli", "Hex 3's `hex` command wasn't found")
    cmd = ([sys.executable] if path.endswith(".py") else []) + [path, *args]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=30)
    if r.returncode != 0:
        raise HexError("failed", (r.stderr or r.stdout).strip()[:200])
    return r.stdout.strip()


def setting(s, key):
    for part in key.split("."):
        s = s.get(part) if isinstance(s, dict) else None
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", action="store_true")
    a = ap.parse_args()

    if not hex_installed():
        say("fix", "Hex", f"no settings found in {HEX_DIR}. Install Hex from https://anoma.ly/hex and dictate something.")
        return
    try:
        version = cli("--version") if BACKEND == "cli" else "Hex 2 (legacy)"
    except (HexError, OSError, subprocess.TimeoutExpired) as e:
        version = f"version unknown ({e})"
    say("ok", "Hex", f"{version}, data in {HEX_DIR}")

    s = load_json(SETTINGS)
    keep = s.get("history_retention")
    if keep in SHORT:
        if a.fix and BACKEND == "cli":
            try:
                hex_call("settings", "set", "history_retention", "month")
                say("ok", "history retention", f"was {keep!r}, now 'month'")
            except HexError as e:
                say("fix", "history retention", f"{keep!r}, and Hex refused the change: {e.message}")
        else:
            how = "run doctor.py --fix, or" if BACKEND == "cli" else "open Hex's settings and"
            say("fix", "history retention", f"{keep!r}: the gate needs 2 days of evidence for a term and 29 for an "
                                            f"ordinary word. To fix, {how} set History to a month or Forever.")
    else:
        say("ok", "history retention", repr(keep))

    hist = history_entries()
    stamps = [e["timestamp_ms"] for e in hist if e.get("timestamp_ms")]
    days = len({time.strftime("%Y-%m-%d", time.localtime(t / 1000)) for t in stamps})
    say("ok" if days >= 2 else "note", "history", f"{len(hist)} dictations on {days} day(s)"
        + ("" if days >= 2 else ". Nothing can pass the gate until there are 2 days."))

    if BACKEND == "cli":
        vocab = s.get("vocabulary") or []
        if setting(s, "labs.vocabulary_biasing"):
            say("ok", "vocabulary help", f"on, {len(vocab)} term(s)")
        elif a.fix:
            try:
                cli("labs", "on", "vocabulary-biasing")
                say("ok", "vocabulary help", "was off, now on")
            except (HexError, OSError, subprocess.TimeoutExpired) as e:
                say("fix", "vocabulary help", f"off, and Hex refused the change: {e}")
        else:
            say("fix" if vocab else "note", "vocabulary help",
                f"off, so the {len(vocab)} vocabulary term(s) don't affect transcription. It's a Labs feature "
                "for Parakeet models. To turn it on: doctor.py --fix, or `hex labs on vocabulary-biasing`.")

    try:
        md = read_text(os.path.join(os.path.expanduser("~"), ".claude", "CLAUDE.md"))
    except OSError:
        md = ""
    try:
        plugin = "hex-upsert" in read_text(os.path.join(os.path.expanduser("~"), ".claude", "plugins", "installed_plugins.json"))
    except OSError:
        plugin = False
    if MARKER in md:
        say("ok", "tag rule", "in your CLAUDE.md, current version")
    elif plugin and "[heard:" in md:
        say("fix", "tag rule", "your CLAUDE.md has an older copy of the rule. The plugin adds the current one each "
                               "session and says it replaces the old one. Delete the old copy to save the tokens.")
    elif plugin:
        say("ok", "tag rule", "added to each session by the plugin's hook")
    else:
        say("fix", "tag rule", "the plugin isn't installed, so nothing tells Claude to tag mishearings. "
                               "Install it: /plugin marketplace add ACNoonan/hex-upsert, then /plugin install hex-upsert@hex-upsert")

    cutoff, tags, sessions = time.time() - 60 * 86400, 0, 0
    for path in glob.glob(os.path.join(LOGS_DIR, "*", "*.jsonl")):
        if os.path.getmtime(path) < cutoff:
            continue
        n = sum(1 for _, text in assistant_texts(path) for m in TAG.finditer(text)
                if not is_placeholder(m["heard"], m["meant"]))
        tags += n
        sessions += n > 0
    say("ok" if tags else "note", "tags written", f"{tags} in {sessions} session(s) over the last 60 days"
        + ("" if tags else ". None yet: tags appear as Claude corrects mishearings. Run the first-run scan meanwhile."))

    claude = shutil.which("claude")
    say("ok" if claude else "note", "claude command", claude or "not on PATH. Only the weekly job needs it.")
    say("ok" if scheduled() else "note", "weekly job",
        "installed" if scheduled() else "not installed (optional: /hex-upsert schedule)")
    try:
        applied = sorted(f for f in os.listdir(os.path.join(STATE, "applied")) if f.endswith(".json"))
    except OSError:
        applied = []
    say("ok" if applied else "note", "last apply", applied[-1][:-5] + " (take it back: upsert.py --undo)" if applied else "none yet")

    n = rows.count("fix")
    print(f"\n{n} thing(s) to fix." if n else "\nAll set.")


if __name__ == "__main__":
    main()
