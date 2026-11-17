#!/usr/bin/env python3
"""Unattended run, meant for launchd: collect -> occurrences -> label -> gate -> apply -> notify.

Private working data goes to ~/Library/Application Support/hex-upsert/runs/<date>/, never a repo.
A seed file of hand-found pairs, if present, lives at ~/Library/Application Support/hex-upsert/seed.json.

Modes:
  default       find safe corrections, save the plan, notify ("run /hex-upsert to apply")
  --auto-apply  also apply them, then notify what was learned

Safety:
  - skips the run if Hex transcribed anything in the last --idle-minutes (default 30)
  - applies replacements only, never recognition hints
  - quits Hex gracefully, writes, relaunches, and rolls back if Hex won't start (upsert.py)
  - --dry-run does everything except quitting Hex and writing settings
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from hexpaths import STATE, history_entries  # noqa: E402


def py(script, *args):
    r = subprocess.run([sys.executable, os.path.join(HERE, script), *args], capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    if r.returncode != 0:
        raise SystemExit(f"{script} failed")
    return r.stdout


def keychain_token():
    """A `claude setup-token` token stored by schedule.sh --store-token. It outlives the normal login."""
    r = subprocess.run(["security", "find-generic-password", "-s", "hex-upsert", "-a", "claude-oauth-token", "-w"],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def notify(title, text):
    text = text.replace('"', "'")[:240]
    subprocess.run(["osascript", "-e", f'display notification "{text}" with title "{title}"'], capture_output=True)


def hex_running():
    return subprocess.run(["pgrep", "-f", "Hex.app/Contents/MacOS/hex"], capture_output=True).returncode == 0


def quit_hex(timeout=30):
    subprocess.run(["osascript", "-e", 'tell application "Hex" to quit'], capture_output=True)
    for _ in range(timeout):
        if not hex_running():
            return True
        time.sleep(1)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--auto-apply", action="store_true", help="apply safe replacements without asking")
    ap.add_argument("--idle-minutes", type=float, default=30)
    a = ap.parse_args()

    stamp = dt.datetime.now().strftime("%Y-%m-%d-%H%M")
    print(f"== hex-upsert weekly run {stamp}")
    hist = history_entries()
    last = max((e.get("timestamp_ms") or 0 for e in hist), default=0) / 1000
    if time.time() - last < a.idle_minutes * 60:
        print("Hex was used in the last %d minutes; skipping" % a.idle_minutes)
        return
    os.makedirs(STATE, exist_ok=True)
    open(os.path.join(STATE, "last_run"), "w").write(str(int(time.time())))

    token = keychain_token()
    if token:
        os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = token  # label.py passes this one through
    print("auth: " + ("setup-token from Keychain" if token else "claude login"))

    w = os.path.join(STATE, "runs", stamp)
    os.makedirs(w, exist_ok=True)
    cand, labels, plan = (os.path.join(w, f) for f in ("candidates.json", "labels.json", "plan.json"))
    seed = os.path.join(STATE, "seed.json")
    py("collect.py", "--days", "60", "--out", cand, *(["--seed", seed] if os.path.exists(seed) else []))
    py("occurrences.py", cand, "--out", labels)
    try:
        py("label.py", labels)
    except SystemExit:
        notify("Hex upsert", "Labelling failed. Your Claude login or setup-token may have expired: run claude auth login, or schedule.sh --store-token. Log: ~/Library/Logs/hex-upsert.log")
        raise
    py("gate.py", cand, labels, "--out", plan)

    dry = py("upsert.py", plan)
    new = [l for l in dry.splitlines() if l.startswith("+ replacement")]
    report = os.path.join(w, "report.txt")
    if not new:
        open(report, "w").write("no new replacements\n" + dry)
        print("no new replacements")
        return
    if a.dry_run:
        open(report, "w").write("DRY RUN, would add:\n" + "\n".join(new) + "\n")
        print("dry run; not applying")
        return
    pairs = [l.split("replacement", 1)[1].strip() for l in new]
    if not a.auto_apply:
        pending = os.path.join(STATE, "pending.json")
        open(pending, "w").write(open(plan).read())
        open(report, "w").write("ready to apply:\n" + "\n".join(new) + "\n")
        notify("Hex upsert: %d correction%s ready" % (len(pairs), "" if len(pairs) == 1 else "s"),
               "; ".join(pairs) + ". Ask Claude Code to run hex-upsert to review and apply.")
        print("notify-only; plan saved to " + pending)
        return
    if hex_running() and not quit_hex():
        notify("Hex upsert", "Hex didn't quit, so nothing was changed.")
        raise SystemExit("Hex did not quit")
    try:
        out = py("upsert.py", plan, "--apply")
    except SystemExit:
        notify("Hex upsert", "Applying failed and the settings were rolled back. See " + report)
        open(report, "w").write("FAILED, rolled back\n")
        raise
    open(report, "w").write(out)
    notify("Hex learned %d correction%s" % (len(pairs), "" if len(pairs) == 1 else "s"), "; ".join(pairs))


if __name__ == "__main__":
    main()
