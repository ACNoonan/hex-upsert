# hex-upsert-skill

A Claude Code skill that learns from the dictation mistakes Claude already corrects, and turns the
safe ones into [Hex](https://github.com/anomalyco/hex) replacements and recognition hints.

**Status: v0.2, early.** A Claude Code plugin for macOS. Built and tested against Hex 2.3.1.

## Install

You need macOS, [Hex 2](https://github.com/anomalyco/hex) and Claude Code. In Claude Code:

```
/plugin marketplace add ACNoonan/hex-upsert-skill
/plugin install hex-upsert@hex-upsert
```

Set Hex's history retention to 30 days or Forever in its settings. The gate checks every
pair against your own transcripts, so it needs history to work with.

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

## What it reads, and where it goes

- **Read locally:** your Claude Code session logs (`~/.claude/projects/`, only the assistant's
  `[heard → meant]` tags, from the last 60 days) and Hex's history
  (`~/Library/Application Support/voice-control/history.json`).
- **Sent to Claude:** to label a pair, Claude reads a snippet of about 140 characters around each
  match in your Hex history. In the default mode that happens inside your own Claude Code
  session. In scheduled mode it goes through headless `claude -p` on your subscription.
  Nothing goes anywhere else.
- **Written:** only Hex's `settings.json`, only after a yes (or with `--auto-apply`), always
  with a timestamped backup next to it. Working files stay in
  `~/Library/Application Support/hex-upsert/`.
- **Refused:** if Hex's settings don't have the shape this tool expects (say, after a Hex
  update), it writes nothing and tells you which field changed.

## Run it unattended (optional)

Ask Claude to run `hex-upsert schedule`, or run `skills/hex-upsert/scripts/schedule.sh` yourself.
It installs a launchd job (`local.hex-upsert`) that runs Sundays at 04:00:

- It skips the run if Hex was used in the last 30 minutes.
- Headless `claude -p` labels each occurrence twice. Any disagreement becomes `unclear`, so
  one judge flip can't decide a pair. The installer refuses unless you're logged in with a
  Claude subscription, and the run strips API keys, so it never bills an API account.
- By default it sends a notification when safe corrections are ready, and the next Claude
  session offers to apply them. With `schedule --auto-apply` it applies replacements itself
  (never recognition hints), relaunches Hex, rolls back if Hex won't start, and notifies you.
- Your normal `claude` login expires every few weeks. To keep the job running, run
  `schedule.sh --store-token` once. It runs `claude setup-token` (a long-lived subscription
  token), asks you to paste the token into a hidden prompt, checks it with one tiny call, and
  stores it in your login Keychain, not in the launchd file. The job reads it at run time.
- If labelling fails, for instance because a login or token expired, it notifies you.

Run data stays in `~/Library/Application Support/hex-upsert/`. Remove the job, and the Keychain token, with
`schedule.sh --uninstall`. Re-run `schedule.sh` after updating: launchd can't read
`~/Documents`, so the job runs a copy of the scripts.

## Try it without installing

```sh
./examples/run_demo.sh
```

This runs the whole pipeline on synthetic data in a temp folder. It touches nothing else.

How the gate decides is in [`docs/gate.md`](docs/gate.md).

## The idea

Hex transcribes speech into Claude Code. When a word comes out wrong, Claude usually reads the
intended meaning and says what it assumed. That correction is lost after the session. This skill
mines those corrections and proposes the ones that are safe to apply to every transcript.

A Hex replacement is a literal, context-free find-and-replace. A naive rule like `sequel → SQL`
would also rewrite every real "sequel". So the skill only promotes a pair when the misheard form is
almost never meant literally, using a zero-failure lower confidence bound on precision. Context
dependent errors stay with Claude.

## First mining run (2026-11-15)

Aggregate numbers only. The raw data stays private.

- 41 correction notes found in Claude Code logs (29 mishearings, 12 typed typos), from 98 regex
  candidates, all hand-checked.
- Counting corrections per occurrence badly understates errors: Claude flags a mishearing once,
  not every time. One name scored 0.016 on that ratio and its hand-checked error rate was 66 of 66.
- Three pairs were safe on a hand read of every Hex occurrence (24/24, 32/32 and 66/66 errors).

## Roadmap

1. Measure word error rate before and after, with Hex's `benchmark-transcription` command.
2. Recognition hints for models that support them (Parakeet doesn't, and Hex won't start with them set).
3. Re-check the settings shape automatically after each Hex update.
