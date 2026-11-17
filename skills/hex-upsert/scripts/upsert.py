#!/usr/bin/env python3
"""Step 4: upsert a gate plan into Hex 2's settings.json.

Dry run by default: prints what would change. With --apply it refuses while Hex is running
(Hex rewrites settings.json from memory), backs the file up next to itself, writes, then
relaunches Hex and checks it stays up. If Hex won't start, it restores the backup and relaunches.

Hints are opt-in (--hints). Hex refuses to START, not just to transcribe, when the selected
model doesn't support recognition hints (Parakeet Unified English, learned 2026-11-17).

  replacements: upserted into dictation_processing.default_mode.replacements by matched_phrase
                (case-insensitive); existing entries with a different output are reported, not changed
  hints:        merged into transcription.recognition_hints (comma-separated, de-duplicated)
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from hexpaths import SETTINGS, load_json  # noqa: E402


def hex_running():
    r = subprocess.run(["pgrep", "-f", "Hex.app/Contents/MacOS/hex"], capture_output=True)
    return r.returncode == 0


TESTED = ["2.3.1"]
REPLACEMENT_KEYS = {"matched_phrase", "output"}


def hex_version():
    for app in ("/Applications/Hex.app", os.path.expanduser("~/Applications/Hex.app")):
        r = subprocess.run(["defaults", "read", f"{app}/Contents/Info", "CFBundleShortVersionString"],
                           capture_output=True, text=True)
        if r.returncode == 0:
            return r.stdout.strip()
    return "unknown"


def schema_problem(s):
    """Refuse to write unless settings.json looks the way Hex 2.3.x laid it out. A Hex update that
    moves or reshapes replacements would otherwise get a file it can't read."""
    if not isinstance(s, dict):
        return "top level is not an object"
    mode = (s.get("dictation_processing") or {}).get("default_mode")
    if not isinstance(mode, dict):
        return "no dictation_processing.default_mode"
    reps = mode.get("replacements", [])
    if not isinstance(reps, list):
        return "replacements is not a list"
    for r in reps:
        if not isinstance(r, dict) or set(r) != REPLACEMENT_KEYS or not all(isinstance(v, str) for v in r.values()):
            return f"a replacement has fields {sorted(r) if isinstance(r, dict) else type(r).__name__}, expected {sorted(REPLACEMENT_KEYS)}"
    tr = s.get("transcription")
    if tr is not None and not isinstance(tr.get("recognition_hints", ""), str):
        return "transcription.recognition_hints is not a string"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plan")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--hints", action="store_true", help="also write recognition hints")
    a = ap.parse_args()

    plan = load_json(a.plan)
    s = load_json(SETTINGS)
    version = hex_version()
    problem = schema_problem(s)
    if problem:
        sys.exit(f"Hex {version}: settings.json isn't in the shape this tool was built for ({problem}). "
                 f"Nothing was written. Built against Hex {', '.join(TESTED)}; please open an issue.")
    if version not in TESTED:
        print(f"note: Hex {version} is untested (built against {', '.join(TESTED)}); the settings shape still matches.")
    mode = s["dictation_processing"]["default_mode"]
    reps = mode.setdefault("replacements", [])
    by_phrase = {r["matched_phrase"].strip().lower(): r for r in reps}

    added, conflicts = [], []
    for r in plan["replacements"]:
        cur = by_phrase.get(r["matched_phrase"].strip().lower())
        if cur is None:
            reps.append({"matched_phrase": r["matched_phrase"], "output": r["output"]})
            added.append(r)
        elif cur["output"] != r["output"]:
            conflicts.append((cur, r))

    new_hints = []
    model = (s.get("transcription") or {}).get("model") or ""
    if a.hints and model.startswith("parakeet"):
        sys.exit(f"model {model!r} does not support recognition hints; Hex would fail to start. Drop --hints.")
    if a.hints:
        tr = s.setdefault("transcription", {})
        have = [h.strip() for h in (tr.get("recognition_hints") or "").split(",") if h.strip()]
        lower = {h.lower() for h in have}
        new_hints = [h for h in plan.get("hints", []) if h.lower() not in lower]
        tr["recognition_hints"] = ", ".join(have + new_hints)

    for r in added:
        print(f'+ replacement  "{r["matched_phrase"]}" -> "{r["output"]}"')
    for cur, r in conflicts:
        print(f'! conflict     "{cur["matched_phrase"]}" is "{cur["output"]}" in Hex, plan says "{r["output"]}" (left alone)')
    for h in new_hints:
        print(f"+ hint         {h}")
    if not (added or new_hints):
        print("nothing to change")
        return
    if not a.apply:
        print("\ndry run. Re-run with --apply after quitting Hex.")
        return
    if "HEX_APPLICATION_SUPPORT_DIR" not in os.environ and hex_running():
        sys.exit("Hex is running. Quit it first (it rewrites settings.json on exit), then re-run.")
    backup = f"{SETTINGS}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(SETTINGS, backup)
    tmp = SETTINGS + ".tmp"
    with open(tmp, "w") as f:
        json.dump(s, f, indent=2, ensure_ascii=False)
    os.replace(tmp, SETTINGS)
    print(f"\nwrote {SETTINGS}\nbackup {backup}")
    if "HEX_APPLICATION_SUPPORT_DIR" in os.environ:
        return
    if launch_ok():
        print("Hex relaunched and is running")
        return
    shutil.copy2(backup, SETTINGS)
    ok = launch_ok()
    sys.exit("Hex would not start with the new settings. Restored the backup; Hex "
             + ("is running again." if ok else "STILL won't start. Check ~/Library/Application Support/voice-control/logs/process.log"))


def launch_ok(wait=6):
    subprocess.run(["open", "-a", "Hex"], capture_output=True)
    time.sleep(wait)
    return hex_running()


if __name__ == "__main__":
    main()
