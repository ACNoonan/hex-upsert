"""Shared paths and Hex 2 file helpers.

Hex 2 (bundle com.kitlangton.hex2) keeps its data in ~/Library/Application Support/voice-control/.
The binary honours HEX_APPLICATION_SUPPORT_DIR, so we do too; tests point it at examples/.
"""
import json
import os
import re

HEX_DIR = os.environ.get(
    "HEX_APPLICATION_SUPPORT_DIR",
    os.path.expanduser("~/Library/Application Support/voice-control"),
)
LOGS_DIR = os.environ.get("CLAUDE_PROJECTS_DIR", os.path.expanduser("~/.claude/projects"))
STATE = os.environ.get(
    "HEX_UPSERT_STATE", os.path.expanduser("~/Library/Application Support/hex-upsert"))
SETTINGS = os.path.join(HEX_DIR, "settings.json")
HISTORY = os.path.join(HEX_DIR, "history.json")


def load_json(path):
    with open(path) as f:
        return json.load(f)


def history_entries():
    """Hex 2 history: {"version", "next_id", "entries": [{id, timestamp_ms, raw_text, final_text, ...}]}."""
    if not os.path.exists(HISTORY):
        return []
    return load_json(HISTORY).get("entries", [])


def phrase_regex(phrase):
    """The same matching Hex uses for a replacement: literal, case-insensitive, whole word."""
    return re.compile(r"(?<!\w)" + re.escape(phrase.strip()) + r"(?!\w)", re.I)
