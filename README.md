# hex-upsert

hex-upsert is a Claude Code plugin for [Hex](https://github.com/anomalyco/hex) dictation. It
turns the mishearings Claude already corrects into Hex replacements, and only the ones that are
safe in every sentence.

## Why it exists

Hex transcribes speech into Claude Code. When a word comes out wrong, Claude usually reads the
intended meaning and says what it assumed. That correction is lost after the session. hex-upsert
mines those corrections and proposes the ones that are safe to apply to every transcript.

A Hex replacement is a literal, context-free find-and-replace. A naive rule like `sequel → SQL`
would also rewrite every real "sequel". So hex-upsert only promotes a pair when the misheard form
is almost never meant literally, using a zero-failure lower confidence bound on precision. Context
dependent errors stay with Claude.

## How it fits with Hex's own features

Hex 3 already has two places for a mishearing. Global replacements rewrite one piece of text as
another. Vocabulary holds a name plus the "sounds like" spellings a transcript shows instead.
Both rely on you to notice the mishearing and type it in, and neither tells you whether a rule
is safe to apply everywhere.

hex-upsert does those two parts. It finds the pairs in the corrections Claude already made,
checks each one against your own Hex history, and writes the safe ones to Global replacements.
If you ask, it also adds the intended word to Vocabulary, with the misheard forms as its "sounds
like" spellings. On Parakeet models, Hex uses Vocabulary while transcribing only with Labs ›
Vocabulary help on.

## Install

You need [Hex](https://anoma.ly/hex), Claude Code and Python 3.9 or later on your PATH. In Claude Code:

```
/plugin marketplace add ACNoonan/hex-upsert
/plugin install hex-upsert@hex-upsert
```

Set Hex's history retention to 30 days or Forever in its settings (Hex 3 keeps 7 days by
default). The gate checks every pair against your own transcripts, so it needs history to work
with.

That's all the setup the default mode needs:

- **Every session**, a `SessionStart` hook tells Claude to tag the mishearings it fixes, as
  `[heard: "X" → meant: "Y"]`. You don't edit your `CLAUDE.md`. If your `CLAUDE.md` already
  has the rule, the hook skips it.
- **Once a week**, on your first Claude Code start, the hook runs the cheap read-only steps
  (about 2 seconds, no model call). If a misheard pair has new evidence on 2 or more days, the
  least any replacement needs, Claude mentions it once and offers to run the skill.
- **The skill** (`/hex-upsert:hex-upsert`) labels every occurrence in your session, gates it
  and shows you the result. It changes Hex only after you say yes. Once you've reviewed a pair,
  the hook stays quiet about it until new occurrences turn up.

## What it's been tested on

**v0.3, early.** It works with Hex 3 on macOS, Linux and Windows, and with Hex 2.3.1 on macOS.

| | Tested how |
|---|---|
| Hex 2.3.1, macOS | On a real install, daily |
| Hex 3.4.0, macOS | On a real install: settings read, replacements applied live through `hex settings apply` |
| Hex 3, Linux and Windows | Against a test double of Hex's `hex` CLI, built from the Hex 3.4.0 source and checked against the real macOS replies. Reports welcome |
| Linux, Windows | The test suite runs there in CI, including installing and removing the weekly job |

## What it reads, and where it goes

- **Read locally:** your Claude Code session logs (`~/.claude/projects/`, only the assistant's
  `[heard → meant]` tags, from the last 60 days) and Hex's `history.json`:

  | Hex | Data folder |
  |---|---|
  | Hex 3, macOS | `~/Library/Application Support/hex` |
  | Hex 3, Linux | `$XDG_DATA_HOME/hex`, else `~/.local/share/hex` |
  | Hex 3, Windows | `%APPDATA%\hex` |
  | Hex 2, macOS | `~/Library/Application Support/voice-control` |

  Hex 3 imports nothing from Hex 2. If you upgraded, both folders exist: the tool writes to
  Hex 3 and still reads the Hex 2 history as extra evidence.
- **Sent to Claude:** to label a pair, Claude reads a snippet of about 140 characters around each
  match in your Hex history. In the default mode that happens inside your own Claude Code
  session. In scheduled mode it goes through headless `claude -p` on your subscription.
  Nothing goes anywhere else.
- **Written:** only Hex's Global replacements (and vocabulary, if you ask), only after a yes
  (or with `--auto-apply`). On Hex 3 the change goes through Hex's own `hex settings apply`,
  which validates it and applies it live, with the old value saved to `hex-upsert/backups/`. On
  Hex 2 it writes `settings.json` while Hex is quit, with a timestamped backup next to it.
  Working files stay in a `hex-upsert` folder beside Hex's data folder.
- **Refused:** if Hex's settings don't have the shape this tool expects (say, after a Hex
  update), it writes nothing and tells you which field changed.

## Run it unattended (optional)

Ask Claude to run `hex-upsert schedule`, or run the installer yourself. Either way it installs a
job that runs Sundays at 04:00, and a missed run happens at the next chance:

| OS | Installer | Job |
|---|---|---|
| macOS | `sh skills/hex-upsert/scripts/schedule.sh` | launchd agent `local.hex-upsert` |
| Linux | `python3 skills/hex-upsert/scripts/schedule.py` | systemd user timer `hex-upsert.timer`. It runs only while you're logged in, unless you run `loginctl enable-linger` |
| Windows | `python skills\hex-upsert\scripts\schedule.py` | Task Scheduler task `hex-upsert`. A console window may flash when it runs |

What the job does:

- It skips the run if Hex was used in the last 30 minutes.
- Headless `claude -p` labels each occurrence twice. Any disagreement becomes `unclear`, so
  one judge flip can't decide a pair. The installer refuses unless you're logged in with a
  Claude subscription, and the run strips API keys, so it never bills an API account.
- By default it sends a notification when safe corrections are ready, and the next Claude
  session offers to apply them. With `schedule --auto-apply` it applies replacements itself
  (never vocabulary or hints) and notifies you. On Hex 2 it quits Hex for a few seconds,
  relaunches it and rolls back if Hex won't start.
- Your normal `claude` login expires every few weeks. On macOS, to keep the job running, run
  `schedule.sh --store-token` once. It runs `claude setup-token` (a long-lived subscription
  token), asks you to paste the token into a hidden prompt, checks it with one tiny call, and
  stores it in your login Keychain, not in the launchd file. The job reads it at run time.
- If labelling fails, for instance because a login or token expired, it notifies you.

Run data and the log stay in the `hex-upsert` state folder (macOS logs to
`~/Library/Logs/hex-upsert.log`). Remove the job with `--uninstall` on the same installer; on
macOS that also deletes the Keychain token. Re-run the installer after updating: the job runs a
copy of the scripts, so a plugin update can't break a run halfway.

## Try it without installing

```sh
./examples/run_demo.sh
```

This runs the whole pipeline on synthetic data in a temp folder. It touches nothing else.
`python3 tests/run_tests.py` runs the same pipeline against both Hex generations, on any OS.

How the gate decides is in [`docs/gate.md`](docs/gate.md).

## First mining run (2026-11-15)

Aggregate numbers only. The raw data stays private.

- 41 correction notes found in Claude Code logs (29 mishearings, 12 typed typos), from 98 regex
  candidates, all hand-checked.
- Counting corrections per occurrence badly understates errors: Claude flags a mishearing once,
  not every time. One name scored 0.016 on that ratio and its hand-checked error rate was 66 of 66.
- Three pairs were safe on a hand read of every Hex occurrence (24/24, 32/32 and 66/66 errors).

## Roadmap

1. Measure word error rate before and after, with Hex's `benchmark-transcription` command.
2. Verify Hex 3 and the weekly job on a real Linux and Windows desktop.
