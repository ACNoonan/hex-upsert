---
name: hex-upsert
description: Turn the dictation mishearings Claude has corrected into Hex replacements, but only the ones safe to apply to every transcript. Also installs or removes a weekly scheduled run. Use when the user says "/hex-upsert", "update my Hex config", "learn my transcription errors", "what has Hex been mishearing", or when a hex-upsert session note says corrections are ready and the user accepts.
argument-hint: "[schedule [--auto-apply] | unschedule]"
---

# hex-upsert

Hex (anomalyco/hex: Hex 3 on macOS, Linux and Windows, or legacy Hex 2 on macOS) transcribes
the user's speech. When Claude corrects a misheard
word it writes a tag: `[heard: "X" → meant: "Y"]`. This skill mines those tags, checks each pair
against Hex's own history, and proposes replacements that are safe to apply everywhere.

A Hex replacement is literal, case-insensitive and whole-word, with no context. One wrong
replacement corrupts every real use of that word, so the gate is strict on purpose.

Scripts live in `scripts/` next to this file (call that folder `$S`). Work in a fresh folder
under the session's scratchpad or a temp dir (call it `$W`). Never write dictation text into a
git repo. Persistent state lives in a `hex-upsert` folder in the OS's data folder (macOS
`~/Library/Application Support`, Linux `~/.local/share`, Windows `%APPDATA%`); call it `$STATE`.
Use `python3`, or `python` where only that exists (Windows). To see which Hex the scripts found:
`python3 -c "import sys; sys.path.insert(0, '$S'); import hexpaths as h; print(h.BACKEND, h.HEX_DIR, h.hex_cli())"`
(`cli` means Hex 3, `file` means Hex 2).

## Arguments

- `schedule` (macOS only for now; on Linux or Windows say the weekly schedule isn't built yet
  and that the session nudge still works): run `sh $S/schedule.sh` to install a weekly launchd
  job (Sundays 04:00). It finds safe corrections and sends a notification. It never changes Hex
  without a yes. `schedule --auto-apply` also applies them, then notifies. Before running it,
  tell the user what it does: on Hex 2 it quits Hex for a few seconds on Sunday at 04:00, it labels with
  headless `claude -p` on their Claude subscription (the script refuses API-key logins), and
  remove it with `unschedule`. Then confirm they want auto-apply, if they asked for it.
- `schedule` also takes `--store-token`, to keep the job working past the normal login's expiry.
  It's interactive (a browser sign-in, then a hidden paste), so never run it yourself or ask for
  the token. Tell the user to run `sh $S/schedule.sh --store-token` in their own terminal.
- `unschedule`: run `sh $S/schedule.sh --uninstall`. It also deletes the Keychain token.
- No argument: the review below.

## Review

0. **Pending plan.** If `$STATE/pending.json` exists, a
   scheduled run already labelled and gated it. Show its replacements with
   `python3 $S/upsert.py <that file>` (a dry run) and go to step 6. After the user decides
   either way, run `python3 $S/reviewed.py --clear-pending`.

1. **Collect candidates.**
   `python3 $S/collect.py --days 60 --out $W/candidates.json`
   Add `--seed FILE` for pairs the user names in chat (a JSON list of `{"heard", "meant"}`).
   If there are no candidates, say so and stop.

2. **List occurrences.**
   `python3 $S/occurrences.py $W/candidates.json --out $W/labels.json`

3. **Label every occurrence yourself.** Open `$W/labels.json`. For each row, read `context`
   (the match is marked ⟦like this⟧) and set `label` to:
   - `error`: the speaker meant `meant` here
   - `literal`: the speaker meant the heard word itself
   - `unclear`: you can't tell
   Label by reading, not by pattern. Also check that `meant` covers exactly the span of
   `heard`: `sequel query → SQL` would turn "the sequel query" into "the SQL". Fix it to
   `SQL query` in `candidates.json` before you gate. Write the file back. Then pick 5 rows at
   random and re-read them cold. If any label changes, re-check that pair's rows in full.

4. **Gate.**
   `python3 $S/gate.py $W/candidates.json $W/labels.json --out $W/plan.json`
   It prints one row per pair: error days, literal days, the lower bound p_l and a decision.
   Then run `python3 $S/reviewed.py $W/labels.json`, so the weekly session note only comes
   back when there's new evidence.

5. **Report to the user.** Use three buckets: *safe to replace*, *in-context only* (a literal use
   exists, so Claude keeps fixing it in context) and *not enough evidence*. Give the counts
   for each pair. Show any proposed vocabulary terms (Hex 3) or recognition hints (Hex 2)
   separately.

6. **Upsert, only on the user's yes.**
   `python3 $S/upsert.py $W/plan.json` (dry run), then show the diff. After they say yes:
   - **Hex 3:** `python3 $S/upsert.py $W/plan.json --apply`. It goes through Hex's own
     `hex settings apply`, which validates and applies the change live. Hex stays open. The
     old Global mode is saved in `$STATE/backups/`, and `hex settings apply <that file>` undoes it.
     `--hints` adds the proposed terms to Hex's vocabulary, with the heard forms as "sounds
     like" spellings. Transcription uses them only with Labs › Vocabulary help on.
   - **Hex 2:** quit Hex first (macOS: `osascript -e 'tell application "Hex" to quit'`,
     telling them first), then run the same command. The script refuses while Hex is running,
     backs up `settings.json`, writes, relaunches Hex and restores the backup if Hex won't
     start. `--hints` writes recognition hints, and the script refuses them on Parakeet
     models: Hex 2 won't even launch with hints set on a model that doesn't support them.

## The gate, in one paragraph

Occurrences count once per calendar day. Any literal day means *in-context only*. A rare form
(a multi-word phrase, or a single word missing from the bundled `data/words.txt.gz`, the
public-domain Webster's 2nd list macOS ships as `/usr/share/dict/words`) needs at least 2
error days and no literal ones. A common single word needs the one-sided 95% lower bound on
precision to reach 0.9. With every day an error, that bound is 0.05^(1/n), so it needs 29 clean
days. The derivation is in `docs/gate.md` in the repo.
