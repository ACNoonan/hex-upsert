# Structure — hex-upsert

**Kind: artifact (public tool).** S1 applies: root is a closed set of at most 12 non-config
files. S2–S5 do not apply. This repo ships a tool and holds no ledger. Any measurement worth
keeping goes in this README as aggregate numbers, with the method in `docs/`.

*Created 2026-11-17 by Adam's choice of kind and name.* Standard:
[`command-center/standard/artifact.md`](../command-center/standard/artifact.md).

## The one rule

> **Everything here must run for a stranger, from a clean checkout.**

## The privacy rule

Adam's dictation text, Hex history, audio and Claude Code session logs never get committed. They
live in `.private/`, which is gitignored. Public examples are synthetic.

## Layout

| Path | What it holds |
|---|---|
| `README.md` | What the skill does, how to install it, the aggregate result |
| `STRUCTURE.md` | This file |
| `PRIVACY.md` | What the plugin reads, writes and sends. The plugin manifest links to it for directory listings |
| `skills/hex-upsert/` | The Claude Code skill (`SKILL.md`), its scripts, the schedulers (launchd, systemd, Task Scheduler) and `data/words.txt.gz` (the gate's word-frequency list, CC BY-SA 4.0, see `data/NOTICE.md`) |
| `hooks/` | The plugin's SessionStart hook config |
| `.claude-plugin/` | Plugin manifest, the single-plugin marketplace and `icon.png` (the listing icon, 1024 px) |
| `docs/` | Method notes, such as the precision gate, and `icon.svg` (the icon's source), and `social-preview.png` (the image GitHub shows when the repo is shared) |
| `examples/` | Synthetic demo data |
| `tests/` | `run_tests.py` (end to end, any OS), `fake_hex.py`, a test double of Hex 3's `hex` CLI, and `tag_rule_eval.py` with its cases, a check of the tag rule that calls Claude and so stays out of CI |
| `.github/workflows/` | CI: the tests on macOS, Linux and Windows |
| `.private/` | Gitignored. Adam's real mining runs, one dated folder each |
