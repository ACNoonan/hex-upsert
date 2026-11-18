#!/usr/bin/env python3
"""Step 4: upsert a gate plan into Hex's Global replacements.

Dry run by default: prints what would change. --apply writes it.

  replacements: upserted into dictation_processing.default_mode.replacements by matched_phrase
                (case-insensitive); existing entries with a different output are reported, not changed
  --hints:      Hex 3: added to the shared vocabulary (`hex vocabulary add`), with each pair's heard
                form as a "sounds like" spelling. Hex 2: merged into transcription.recognition_hints.

Hex 3 (macOS, Linux, Windows): the change goes through `hex settings apply`, which validates it
and saves it live, or writes settings.json itself when Hex is stopped. Hex stays open. The old
Global mode is saved to <state>/backups/ first.

Hex 2 (macOS, legacy): refuses while Hex is running (it rewrites settings.json from memory),
backs the file up next to itself, writes, relaunches Hex and checks it stays up. If Hex won't
start, it restores the backup and relaunches. Hints are refused on Parakeet models: Hex 2
won't even launch with hints set on a model that doesn't support them (learned 2026-11-17).
"""
import argparse
import json
import os
import plistlib
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from hexpaths import (BACKEND, SETTINGS, STATE, SYSTEM, HexError, hex_call,  # noqa: E402
                      load_json, save_json)

KEY = "dictation_processing.default_mode"
TESTED = {"cli": ["3.4.0 (against a test double built from its source; please report)"], "file": ["2.3.1"]}


def schema_problem(mode):
    """Refuse to write unless the Global mode looks the way Hex lays it out. A Hex update that
    moves or reshapes replacements would otherwise get a value it can't read."""
    if not isinstance(mode, dict):
        return f"no {KEY}"
    reps = mode.get("replacements", [])
    if not isinstance(reps, list):
        return "replacements is not a list"
    for r in reps:
        if not isinstance(r, dict) or set(r) != {"matched_phrase", "output"} \
                or not all(isinstance(v, str) for v in r.values()):
            return f"a replacement has fields {sorted(r) if isinstance(r, dict) else type(r).__name__}, " \
                   "expected ['matched_phrase', 'output']"
    return None


# ---- reading the current Global mode -------------------------------------------------------

def current_mode():
    """(mode, how it was read). Hex 3: ask the running Hex, else read the file it saved."""
    if BACKEND == "cli":
        try:
            reply = hex_call("settings", "get", KEY)
            for s in reply.get("settings", []):
                if s.get("key") == KEY:
                    return s.get("value"), "hex settings get"
            return None, "hex settings get"
        except HexError as e:
            if e.code != "not-running":
                raise
    s = load_json(SETTINGS)
    return (s.get("dictation_processing") or {}).get("default_mode"), SETTINGS


def merge(mode, plan):
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
    return added, conflicts


def hint_spellings(plan):
    """term -> the heard forms it was misheard as, for Hex 3's "sounds like" column."""
    out = {}
    for h in plan.get("hints", []):
        out[h] = sorted({r["heard"] for r in plan.get("rows", []) if r.get("meant") == h and r.get("heard")})
    return out


# ---- Hex 3 ---------------------------------------------------------------------------------

def apply_cli(mode, added, hints):
    os.makedirs(os.path.join(STATE, "backups"), exist_ok=True)
    old, _ = current_mode()
    backup = os.path.join(STATE, "backups", f"default_mode-{time.strftime('%Y%m%d-%H%M%S')}.json")
    save_json(backup, {KEY: old}, indent=2)
    if added:
        hex_call("settings", "apply", "-", stdin=json.dumps({KEY: mode}, ensure_ascii=False))
        now, how = current_mode()
        have = {r["matched_phrase"].strip().lower() for r in (now or {}).get("replacements", [])}
        missing = [r["matched_phrase"] for r in added if r["matched_phrase"].strip().lower() not in have]
        if missing:
            sys.exit(f"Hex accepted the change but {how} doesn't show {missing}. To undo: hex settings apply {backup}")
        print(f"\nsaved through Hex's CLI (checked with {how})\nbackup {backup}  (undo: hex settings apply that file)")
    for term, spellings in hints.items():
        args = ["vocabulary", "add", term] + (["--sounds-like", ",".join(spellings)] if spellings else [])
        try:
            hex_call(*args)
            print(f"vocabulary: added {term}")
        except HexError as e:
            print(f"vocabulary: {term} not added: {e.message} ({e.code})")
    if hints:
        print("note: Hex uses vocabulary for transcription only with Labs › Vocabulary help on "
              "(hex labs on vocabulary-biasing); rewriting and search use it either way.")


# ---- Hex 2 (legacy, macOS) -----------------------------------------------------------------

def hex2_running():
    return subprocess.run(["pgrep", "-f", "Hex.app/Contents/MacOS/hex"], capture_output=True).returncode == 0


def hex2_version():
    for app in ("/Applications/Hex.app", os.path.expanduser("~/Applications/Hex.app")):
        try:
            with open(os.path.join(app, "Contents", "Info.plist"), "rb") as f:
                return plistlib.load(f).get("CFBundleShortVersionString", "unknown")
        except (OSError, ValueError):
            continue
    return "unknown"


def launch_ok(wait=6):
    subprocess.run(["open", "-a", "Hex"], capture_output=True)
    time.sleep(wait)
    return hex2_running()


def apply_file(s):
    test_mode = "HEX_APPLICATION_SUPPORT_DIR" in os.environ
    if not test_mode and hex2_running():
        sys.exit("Hex is running. Quit it first (it rewrites settings.json on exit), then re-run.")
    backup = f"{SETTINGS}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(SETTINGS, backup)
    tmp = SETTINGS + ".tmp"
    save_json(tmp, s, indent=2)
    os.replace(tmp, SETTINGS)
    print(f"\nwrote {SETTINGS}\nbackup {backup}")
    if test_mode or SYSTEM != "Darwin":
        return
    if launch_ok():
        print("Hex relaunched and is running")
        return
    shutil.copy2(backup, SETTINGS)
    ok = launch_ok()
    sys.exit("Hex would not start with the new settings. Restored the backup; Hex "
             + ("is running again." if ok else "STILL won't start. Check ~/Library/Application Support/voice-control/logs/process.log"))


# ---- main ----------------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plan")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--hints", action="store_true", help="also add proposed terms (vocabulary or recognition hints)")
    a = ap.parse_args()
    plan = load_json(a.plan)
    gen = "Hex 3" if BACKEND == "cli" else "Hex 2"

    try:
        if BACKEND == "cli":
            mode, source = current_mode()
            s = None
        else:
            s = load_json(SETTINGS)
            mode, source = (s.get("dictation_processing") or {}).get("default_mode") if isinstance(s, dict) else None, SETTINGS
    except (HexError, OSError, ValueError) as e:
        sys.exit(f"Couldn't read Hex's settings: {e}. Nothing was written.")
    problem = schema_problem(mode)
    if problem:
        sys.exit(f"{gen}: the Global mode from {source} isn't in the shape this tool was built for ({problem}). "
                 f"Nothing was written. Built against Hex {', '.join(TESTED[BACKEND])}; please open an issue.")
    if BACKEND == "file" and SYSTEM == "Darwin" and "HEX_APPLICATION_SUPPORT_DIR" not in os.environ:
        v = hex2_version()
        if v not in TESTED["file"]:
            print(f"note: Hex {v} is untested (built against {', '.join(TESTED['file'])}); the settings shape still matches.")

    added, conflicts = merge(mode, plan)

    hints, new_hints = {}, []
    if a.hints and BACKEND == "cli":
        try:
            saved = load_json(SETTINGS).get("vocabulary") or []
        except (OSError, ValueError):
            saved = []
        have = {(v if isinstance(v, str) else v.get("term", "")).lower() for v in saved}
        hints = {t: sp for t, sp in hint_spellings(plan).items() if t.lower() not in have}
        new_hints = list(hints)
    elif a.hints:
        model = (s.get("transcription") or {}).get("model") or ""
        if model.startswith("parakeet"):
            sys.exit(f"model {model!r} does not support recognition hints; Hex 2 would fail to start. Drop --hints.")
        tr = s.setdefault("transcription", {})
        if not isinstance(tr.get("recognition_hints", ""), str):
            sys.exit("transcription.recognition_hints is not a string. Nothing was written.")
        have = [h.strip() for h in (tr.get("recognition_hints") or "").split(",") if h.strip()]
        lower = {h.lower() for h in have}
        new_hints = [h for h in plan.get("hints", []) if h.lower() not in lower]
        tr["recognition_hints"] = ", ".join(have + new_hints)

    for r in added:
        print(f'+ replacement  "{r["matched_phrase"]}" -> "{r["output"]}"')
    for cur, r in conflicts:
        print(f'! conflict     "{cur["matched_phrase"]}" is "{cur["output"]}" in Hex, plan says "{r["output"]}" (left alone)')
    for h in new_hints:
        extra = f"  (sounds like: {', '.join(hints[h])})" if hints.get(h) else ""
        print(f"+ {'vocabulary' if BACKEND == 'cli' else 'hint':<12} {h}{extra}")
    if not (added or new_hints):
        print("nothing to change")
        return
    if not a.apply:
        print("\ndry run. Re-run with --apply" + ("." if BACKEND == "cli" else " after quitting Hex."))
        return
    try:
        if BACKEND == "cli":
            apply_cli(mode, added, hints)
        else:
            apply_file(s)
    except HexError as e:
        sys.exit(f"Hex refused the change: {e.message} ({e.code}). Nothing was written.")


if __name__ == "__main__":
    main()
