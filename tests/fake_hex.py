#!/usr/bin/env python3
"""A test double of Hex 3's `hex` CLI: only the commands hex-upsert uses, with the reply shapes
from anomalyco/hex docs/cli.md (control protocol version 4). It works on the settings.json in
HEX_APPLICATION_SUPPORT_DIR. FAKE_HEX_STOPPED=1 acts as if Hex isn't running.

  hex settings get <key> --json
  hex settings apply <file|-> --json        works stopped too: writes settings.json directly
  hex vocabulary add <term> [--sounds-like a,b] --json
"""
import json
import os
import sys

V = 4
DIR = os.environ["HEX_APPLICATION_SUPPORT_DIR"]
SETTINGS = os.path.join(DIR, "settings.json")
STOPPED = os.environ.get("FAKE_HEX_STOPPED") == "1"


def reply(obj, code=0):
    print(json.dumps({"version": V, **obj}, ensure_ascii=False))
    sys.exit(code)


def error(code, message, exit_code=1):
    reply({"status": "error", "code": code, "message": message}, exit_code)


def load():
    with open(SETTINGS, encoding="utf-8") as f:
        return json.load(f)


def save(s):
    with open(SETTINGS, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2, ensure_ascii=False)


def get_path(s, key):
    for part in key.split("."):
        if not isinstance(s, dict) or part not in s:
            return None
        s = s[part]
    return s


def set_path(s, key, value):
    parts = key.split(".")
    for part in parts[:-1]:
        s = s.setdefault(part, {})
    s[parts[-1]] = value


def check_mode(key, mode):
    """What Hex's serde would refuse: replacements that aren't {matched_phrase, output} strings."""
    if not isinstance(mode, dict):
        error("invalid-value", f"{key}: expected an object")
    for r in mode.get("replacements", []):
        if not isinstance(r, dict) or not isinstance(r.get("matched_phrase"), str) or not isinstance(r.get("output"), str):
            error("invalid-value", f"{key}: invalid replacement {r!r}")


def main():
    args = [a for a in sys.argv[1:] if a != "--json"]
    if args[:2] == ["settings", "get"]:
        if STOPPED:
            error("not-running", "Hex isn't running", 3)
        key = args[2]
        reply({"status": "settings", "settings": [
            {"key": key, "value": get_path(load(), key), "kind": "json", "writable": True, "about": "fake"}]})
    if args[:2] == ["settings", "apply"]:
        src = sys.stdin.read() if args[2] == "-" else open(args[2], encoding="utf-8").read()
        values = json.loads(src)
        s = load()
        for key, value in values.items():
            if key.startswith("dictation_processing."):
                check_mode(key, value)
            set_path(s, key, value)
        save(s)
        reply({"status": "done", "message": f"Applied {len(values)} setting(s)", "changed": True})
    if args[:2] == ["vocabulary", "add"]:
        if STOPPED:
            error("not-running", "Hex isn't running", 3)
        term = args[2]
        spell = args[args.index("--sounds-like") + 1].split(",") if "--sounds-like" in args else []
        s = load()
        vocab = s.setdefault("vocabulary", [])
        cur = next((v for v in vocab if v["term"].lower() == term.lower()), None)
        if cur is None:
            vocab.append({"term": term, **({"sounds_like": spell} if spell else {})})
        else:
            cur["sounds_like"] = sorted(set(cur.get("sounds_like", [])) | set(spell))
        save(s)
        reply({"status": "done", "message": f"Added {term}", "changed": True})
    print(f"fake hex: unsupported {args}", file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
