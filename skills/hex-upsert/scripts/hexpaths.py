"""Where Hex keeps its data on each OS, which Hex is installed, and shared file helpers.

Two Hex generations are supported:

  Hex 3 (anomalyco/hex, bundle anomaly.hex; macOS, Linux, Windows)
      data:  macOS   ~/Library/Application Support/hex
             Linux   $XDG_DATA_HOME/hex, else ~/.local/share/hex
             Windows %APPDATA%\\hex
      writes go through its `hex` CLI (`hex settings apply`), which validates and saves the
      change live, or writes settings.json itself when Hex is stopped.
  Hex 2 (com.kitlangton.hex2, macOS only, legacy)
      data:  ~/Library/Application Support/voice-control
      writes go straight to settings.json while Hex is quit (upsert.py).

Hex 3 imports nothing from Hex 2, so after an upgrade both folders exist. Hex 3 wins for
settings, and the Hex 2 history is still read as extra evidence.

HEX_APPLICATION_SUPPORT_DIR points at one data folder (Hex itself honours it too); the tests
point it at examples/. HEX_UPSERT_BACKEND=cli|file forces the write path, HEX_CLI the binary.
"""
import json
import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys

SYSTEM = platform.system()  # Darwin | Linux | Windows

# Dictation text and the ⟦⟧ markers are UTF-8; a Windows console or pipe defaults to cp1252.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def data_dir():
    """The folder Rust's dirs::data_dir() gives Hex on this OS."""
    if SYSTEM == "Darwin":
        return os.path.expanduser("~/Library/Application Support")
    if SYSTEM == "Windows":
        return os.environ.get("APPDATA") or os.path.expanduser(r"~\AppData\Roaming")
    return os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")


HEX3_DIR = os.path.join(data_dir(), "hex")
HEX2_DIR = os.path.expanduser("~/Library/Application Support/voice-control") if SYSTEM == "Darwin" else None


def _detect():
    forced = os.environ.get("HEX_APPLICATION_SUPPORT_DIR")
    if forced:
        return forced, os.environ.get("HEX_UPSERT_BACKEND", "file")
    if os.path.exists(os.path.join(HEX3_DIR, "settings.json")):
        return HEX3_DIR, os.environ.get("HEX_UPSERT_BACKEND", "cli")
    if HEX2_DIR and os.path.exists(os.path.join(HEX2_DIR, "settings.json")):
        return HEX2_DIR, "file"
    return HEX3_DIR, "cli"  # nothing installed yet; Hex 3 is what a new user gets


HEX_DIR, BACKEND = _detect()
SETTINGS = os.path.join(HEX_DIR, "settings.json")
HISTORY = os.path.join(HEX_DIR, "history.json")
LOGS_DIR = os.environ.get("CLAUDE_PROJECTS_DIR", os.path.expanduser(os.path.join("~", ".claude", "projects")))
STATE = os.environ.get("HEX_UPSERT_STATE", os.path.join(data_dir(), "hex-upsert"))
WORDS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "words.txt.gz")


def hex_installed():
    return os.path.exists(SETTINGS)


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, obj, **kw):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, **kw)


def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def write_text(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _entries(path, prefix=""):
    if not os.path.exists(path):
        return []
    out = []
    for e in load_json(path).get("entries", []):
        if prefix:
            e = {**e, "id": f"{prefix}{e['id']}"}
        out.append(e)
    return out


def history_entries():
    """Hex history: {"version", "next_id", "entries": [{id, timestamp_ms, raw_text, final_text, ...}]}.
    Hex 2 and Hex 3 use the same shape. After an upgrade the Hex 2 entries are added with ids
    prefixed "v2-", so they never collide with Hex 3's."""
    entries = _entries(HISTORY)
    if HEX_DIR == HEX3_DIR and HEX2_DIR and "HEX_APPLICATION_SUPPORT_DIR" not in os.environ:
        entries += _entries(os.path.join(HEX2_DIR, "history.json"), prefix="v2-")
    return entries


def phrase_regex(phrase):
    """The same matching Hex uses for a replacement: literal, case-insensitive, whole word."""
    return re.compile(r"(?<!\w)" + re.escape(phrase.strip()) + r"(?!\w)", re.I)


# ---- the Hex 3 `hex` CLI ---------------------------------------------------------------

def _bundle_id(app):
    try:
        with open(os.path.join(app, "Contents", "Info.plist"), "rb") as f:
            return plistlib.load(f).get("CFBundleIdentifier", "")
    except (OSError, ValueError):
        return ""


def hex_cli():
    """Path to Hex 3's `hex` command, or None. Never returns Hex 2's binary: running that with
    arguments would just launch the app."""
    if os.environ.get("HEX_CLI"):
        return os.environ["HEX_CLI"]
    found = []
    if SYSTEM == "Darwin":
        for app in ("/Applications/Hex.app", os.path.expanduser("~/Applications/Hex.app")):
            if _bundle_id(app) not in ("", "com.kitlangton.hex2"):
                found.append(os.path.join(app, "Contents", "MacOS", "hex"))
    elif SYSTEM == "Windows":
        found.append(os.path.join(HEX3_DIR, "bin", "hex.com"))
    else:
        found += [os.path.expanduser("~/.local/bin/hex"), "/usr/bin/hex"]
    on_path = shutil.which("hex")
    if on_path and not (SYSTEM == "Darwin" and "/Hex.app/" in os.path.realpath(on_path)
                        and _bundle_id(os.path.realpath(on_path).split("/Contents/")[0]) == "com.kitlangton.hex2"):
        found.append(on_path)
    return next((p for p in found if os.path.isfile(p)), None)


class HexError(Exception):
    def __init__(self, code, message):
        super().__init__(f"{message} ({code})")
        self.code, self.message = code, message


def hex_call(*args, stdin=None, timeout=30):
    """Run `hex <args> --json` and return the parsed reply. Raises HexError with Hex's own
    code and message on a refusal, and code "not-running" (exit 3) when Hex is stopped."""
    cli = hex_cli()
    if not cli:
        raise HexError("no-cli", "Hex 3's `hex` command wasn't found. Install Hex from https://anoma.ly/hex, "
                                 "or set HEX_CLI to its path.")
    cmd = [cli, *args, "--json"]
    if cli.endswith(".py"):  # the test double
        cmd = [sys.executable, *cmd]
    try:
        r = subprocess.run(cmd, input=stdin, capture_output=True, text=True, encoding="utf-8",
                           timeout=timeout, stdin=None if stdin is not None else subprocess.DEVNULL)
    except OSError as e:
        raise HexError("no-cli", f"couldn't run {cli}: {e}")
    except subprocess.TimeoutExpired:
        raise HexError("timeout", f"`hex {' '.join(args)}` didn't answer within {timeout} s")
    try:
        reply = json.loads(r.stdout)
    except ValueError:
        if r.returncode == 3:
            raise HexError("not-running", "Hex isn't running")
        raise HexError("transport", f"`{os.path.basename(cli)} {' '.join(args)}` exited {r.returncode} "
                                    f"without a JSON reply: {(r.stderr or r.stdout).strip()[:300]}")
    if not isinstance(reply, dict) or "version" not in reply:
        raise HexError("transport", f"{cli} doesn't look like Hex's CLI (reply: {r.stdout[:200]})")
    if reply.get("status") == "error" or r.returncode != 0:
        raise HexError(reply.get("code", "failed"), reply.get("message", r.stderr.strip()[:300]))
    return reply
