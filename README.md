# hex-upsert

hex-upsert is a Claude Code plugin for [Hex](https://github.com/anomalyco/hex) dictation. It
turns the mishearings Claude already corrects into Hex replacements and vocabulary, and only
the ones that are safe in every sentence.

## Install

You need [Hex](https://anoma.ly/hex), Claude Code and Python 3.9 or later on your PATH. In
Claude Code:

```
/plugin marketplace add ACNoonan/hex-upsert
/plugin install hex-upsert@hex-upsert
```

Then run `/hex-upsert:hex-upsert`. The first run checks your setup and scans the Hex history
you already have for words Hex spelled as non-words, so there's something to review on day one.

After that it runs itself:

- **Every session**, a `SessionStart` hook tells Claude to tag a misheard term when it fixes
  one, as `[heard: "X" → meant: "Y"]`. It tags only a term worth teaching Hex, one you'd want
  replaced every time you say it (`pie torch` → `PyTorch`). A dropped or swapped ordinary word
  (`don't` → `do`) gets fixed in context and no tag. You don't edit your `CLAUDE.md`.
- **Once a week**, on your first Claude Code start, the hook runs the cheap read-only steps
  (about 2 seconds, no model call). If a misheard pair has new evidence on 2 or more days,
  Claude mentions it once and offers to run the skill.
- **The skill** labels every occurrence in your session, gates it and shows you the result. It
  changes Hex only after you say yes.

| Say | What happens |
|---|---|
| `/hex-upsert:hex-upsert` | Review: what Hex keeps mishearing, and what's safe to fix |
| `/hex-upsert:hex-upsert doctor` | Setup check: Hex, history retention, vocabulary help, the tag rule |
| `/hex-upsert:hex-upsert undo` | Take back the most recent change, and only that |
| `/hex-upsert:hex-upsert stats` | Per week: mishearings a replacement fixed, and ones that still got through |
| `/hex-upsert:hex-upsert schedule` | Optional weekly unattended run |

## Why it exists

Hex transcribes speech into Claude Code. When a word comes out wrong, Claude usually reads the
intended meaning and says what it assumed. That correction dies with the session, so the next
session makes it again.

In my own logs (60 days, sessions about this plugin left out), 7 names and terms account for
24 of those corrections across 14 sessions, under 15 different spellings. Hex's history shows
why: it wrote one colleague's name wrong 8 times out of 8, and got "Vercel" and "Supabase"
right 0 times. In the last week with no replacements, 18 dictated mishearings of the terms
now covered reached Claude. In the week the replacements went in, Hex fixed 12 before Claude
saw them.

The cost isn't tokens. The 24 correction notes come to about 400 tokens. The cost is the
correction Claude doesn't make. A mishearing that still reads as a sensible sentence passes
without a note: in one session Hex turned "I do think" into "I don't think" and reversed the
instruction. Claude caught that one from context. Nothing guarantees it catches the next, and
a wrong name in a commit message, an email or a search query doesn't look wrong to anyone but
you.

So the fix has to happen before the text reaches Claude, in Hex. A Hex replacement is a
literal, context-free find-and-replace, though, and a naive rule like `sequel → SQL` would also
rewrite every real "sequel". hex-upsert only promotes a pair when the misheard form is almost
never meant literally. It sorts each pair into one of five types and asks each type for the
evidence it needs:

| Type | Example | Becomes a replacement |
|---|---|---|
| The heard form isn't a word | `Superbase` → `Supabase` | after 2 days of evidence for the term |
| A term came out as ordinary words | `clawed code` → `Claude Code` | after 2 days if it's a phrase, 29 clean days if it's one word (`sequel` → `SQL`) |
| Right words, wrong case or spacing | `Agent Mine` → `agentmine` | the same |
| An ordinary word for an ordinary word | `air` → `error` | after 29 clean days, so in practice it stays with Claude |
| Words dropped, added or cut short | `don't` → `do` | never |

The 29 days come from a zero-failure lower confidence bound on precision. Context dependent
errors stay with Claude. How the gate decides is in [`docs/gate.md`](docs/gate.md).

## How it fits with Hex's own features

Hex 3 already has two places for a mishearing. Global replacements rewrite one piece of text as
another. Vocabulary holds a name plus the "sounds like" spellings a transcript shows instead.
Both rely on you to notice the mishearing and type it in, and neither tells you whether a rule
is safe to apply everywhere.

hex-upsert does those two parts. It finds the pairs in the corrections Claude already made and
checks each one against your own Hex history. For a name or term Hex doesn't know, it proposes
a Vocabulary entry first, with the safe misheard forms as its "sounds like" spellings: one
entry covers every way Hex mangles the term. It writes the safe pairs to Global replacements as
the backstop. On Parakeet models, Hex uses Vocabulary while transcribing only with Labs ›
Vocabulary help on, and the setup check offers to turn it on.

## Setup details

- **History.** The gate checks every pair against your own transcripts, so Hex has to keep
  them. Hex 3 keeps 7 days by default. The setup check offers to set it to a month.
- **The tag rule has a version.** If you keep your own copy of the rule in `CLAUDE.md`, put
  `hex-upsert-rule: v2` in it and the hook skips its copy. Without that marker the hook adds
  the current rule, so an old copy never holds you on old wording.
- **Undo.** Every apply is recorded. `undo` removes the replacements and vocabulary terms the
  most recent apply added, and leaves anything you changed since.

## What it's been tested on

**v0.5, early.** It works with Hex 3 on macOS, Linux and Windows, and with Hex 2.3.1 on macOS.

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

## Results so far

Aggregate numbers from one person's data. The raw data stays private.

- **The tag rule** (`tests/tag_rule_eval.py`, 42 synthetic prompts through headless Claude
  Code, 2026-11-19). The current rule tagged a real term in 32 of 32 runs and a non-term in 2
  of 37. Both of those were `wait decay` → `weight decay`, a term of art made of ordinary
  words, which the gate holds to 29 clean days anyway. The first rule tagged a non-term in 12
  of 19 runs: every negation, homophone and truncation it noticed. 16 of 126 calls timed out
  and are left out, so 4 non-term cases have no run under the current rule.
- **Repeats** (2026-11-19, 60 days of logs, sessions about this plugin left out): 7 terms, 24
  corrections by Claude, 14 sessions, 15 spellings, about 400 tokens of correction notes.
- **First week of replacements** (`stats`): in ISO week 46, with no replacements, 18
  mishearings of the terms now covered reached Claude and 0 were fixed. In week 47, when the
  replacements went in, 12 were fixed in Hex and 7 got through.
- **First mining run** (2026-11-15): 41 correction notes in Claude Code logs (29 mishearings,
  12 typed typos), from 98 regex candidates, all hand-checked. Counting corrections per
  occurrence badly understates errors, because Claude flags a mishearing once, not every time.
  One name scored 0.016 on that ratio and its hand-checked error rate was 66 of 66.

## Roadmap

1. Re-run `stats` after a month of replacements, on more than one person's data.
2. Verify Hex 3 and the weekly job on a real Linux and Windows desktop.
