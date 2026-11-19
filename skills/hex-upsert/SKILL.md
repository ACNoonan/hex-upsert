---
name: hex-upsert
description: Turn the dictation mishearings Claude has corrected into Hex replacements and vocabulary, but only the ones safe to apply to every transcript. Also checks the setup, undoes the last change, shows weekly stats, and installs or removes a weekly scheduled run. Use when the user says "/hex-upsert", "update my Hex config", "learn my transcription errors", "what has Hex been mishearing", "undo the Hex changes", "is hex-upsert set up", or when a hex-upsert session note says corrections are ready and the user accepts.
argument-hint: "[doctor | undo | stats | schedule [--auto-apply] | unschedule]"
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

- `schedule`: install a weekly job, Sundays 04:00. On macOS run `sh $S/schedule.sh` (launchd).
  On Linux and Windows run `python3 $S/schedule.py` (`python` on Windows): a systemd user timer
  or a Task Scheduler task. It finds safe corrections and sends a notification. It never changes Hex
  without a yes. `schedule --auto-apply` also applies them, then notifies. Before running it,
  tell the user what it does: on Hex 2 it quits Hex for a few seconds on Sunday at 04:00, it labels with
  headless `claude -p` on their Claude subscription (the script refuses API-key logins), and
  remove it with `unschedule`. Then confirm they want auto-apply, if they asked for it.
- On Linux, mention that user timers run only while the user is logged in unless they run
  `loginctl enable-linger`. On Windows, a console window may flash at 04:00 when it runs.
- `schedule` also takes `--store-token` (macOS only), to keep the job working past the normal login's expiry.
  It's interactive (a browser sign-in, then a hidden paste), so never run it yourself or ask for
  the token. Tell the user to run `sh $S/schedule.sh --store-token` in their own terminal.
- `unschedule`: run `sh $S/schedule.sh --uninstall` (macOS; it also deletes the Keychain token)
  or `python3 $S/schedule.py --uninstall` (Linux, Windows).
- `doctor`: run `python3 $S/doctor.py` and show its lines as they are. It changes nothing.
  If a line says `fix` for history retention or vocabulary help, say what `--fix` would change
  (history kept for a month; Labs › Vocabulary help on, which changes how Parakeet hears every
  dictation) and run `python3 $S/doctor.py --fix` only on a yes.
- `undo`: `python3 $S/upsert.py --undo` shows what the most recent apply added. On a yes, run
  it with `--undo --apply` (Hex 2: quit Hex first, as in step 6). It removes those replacements
  and vocabulary terms and nothing else. Run it again to step back one more apply.
- `stats`: run `python3 $S/stats.py` and show the table: per week, how often a replacement
  fired, how often a misheard form still got through, and how many tags Claude wrote.
- No argument: the review below.

## Review

0. **First run.** If `$STATE/reviewed.json` doesn't exist, this user has never done a review.
   Run `python3 $S/doctor.py` first and deal with any `fix` line as under `doctor` above.
   A new user has few or no tags, so also run the scan:
   `python3 $S/scan.py --out $W/scan.json`
   It lists the forms in Hex's history that aren't in the word list, with snippets. Read each
   one. Most are real words or terms Hex got right (`GitHub`, `backfill`): skip those. For a
   form that is clearly a mishearing of something you can name from the snippets (`Superbase`
   in a sentence about database auth), add `{"heard": "Superbase", "meant": "Supabase"}` to
   `$W/seed.json`. If you can't tell what was meant, ask the user about the few forms that
   show up on 2 or more days, and skip the rest. Pass the file to step 1 with `--seed`.

0b. **Pending plan.** If `$STATE/pending.json` exists, a
   scheduled run already labelled and gated it. Show its replacements with
   `python3 $S/upsert.py <that file>` (a dry run) and go to step 6. After the user decides
   either way, run `python3 $S/reviewed.py --clear-pending`.

1. **Collect candidates.**
   `python3 $S/collect.py --days 60 --out $W/candidates.json`
   Add `--seed FILE` for pairs the user names in chat or the first-run scan found (a JSON
   list of `{"heard", "meant"}`). If there are no candidates, run the scan from step 0 if you
   haven't. If there are still none, say so and stop.
   Then read the list and delete every candidate that isn't a term to teach Hex. The test is
   whether the user would want `heard` turned into `meant` every time they say those words.
   A dropped or swapped ordinary word (`don't` → `do`, `our` → `or`), a negation, or a
   one-off garble of a whole phrase fails it, whatever the tag said. Tell the user which ones
   you dropped.

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
   It prints the proposed vocabulary, then one row per pair: its type, its error days, its
   target's error days, literal days, the lower bound p_l and a decision.
   Check the types by eye. The gate sorts pairs by rule, and a pair in the wrong type gets the
   wrong evidence rule. If one is wrong, say so in the report and leave that pair out.
   Then run `python3 $S/reviewed.py $W/labels.json`, so the weekly session note only comes
   back when there's new evidence.

5. **Report to the user.** Lead with vocabulary: the terms to teach Hex, each with its "sounds
   like" spellings. Drop any term that is really an ordinary word (`Rap` from `rep God`). Then
   the replacements, in three buckets: *safe to replace*, *in-context only* (a literal use
   exists, or words were dropped, so Claude keeps fixing it in context) and *not enough
   evidence*. Give the type and the counts for each pair.

6. **Upsert, only on the user's yes.**
   `python3 $S/upsert.py $W/plan.json --vocabulary` (dry run), then show the diff. On Hex 2
   leave `--vocabulary` off unless the user asks for recognition hints. After they say yes:
   Every apply is recorded, and `/hex-upsert undo` takes the most recent one back. Say so.
   - **Hex 3:** `python3 $S/upsert.py $W/plan.json --vocabulary --apply` (drop `--vocabulary`
     if they only want replacements). It goes through Hex's own
     `hex settings apply`, which validates and applies the change live. Hex stays open. The
     old Global mode is saved in `$STATE/backups/`, and `hex settings apply <that file>` undoes it.
     `--vocabulary` adds the proposed terms to Hex's vocabulary, with the heard forms the gate
     marked safe as "sounds like" spellings. Transcription uses them only with Labs ›
     Vocabulary help on. To leave a term out, delete it from `vocabulary` in the plan first.
   - **Hex 2:** quit Hex first (macOS: `osascript -e 'tell application "Hex" to quit'`,
     telling them first), then run the same command. The script refuses while Hex is running,
     backs up `settings.json`, writes, relaunches Hex and restores the backup if Hex won't
     start. `--vocabulary` writes recognition hints, and the script refuses them on Parakeet
     models: Hex 2 won't even launch with hints set on a model that doesn't support them.

## The gate, in one paragraph

Occurrences count once per calendar day. Any literal day means *in-context only*. The gate sorts
each pair into a type and the type picks the evidence rule. A **non-word** (`Superbase` →
`Supabase`), and a **term-as-words** or **written-form** pair whose heard form is a phrase
(`clawed code` → `Claude Code`, `Agent Mine` → `agentmine`), needs 1 error day of its own and 2
across every heard form of the same target. A **word-swap** (`air` → `error`), and a
term-as-words or written-form pair whose heard form is one ordinary word (`sequel` → `SQL`,
`spit` → `SPIT`), needs the one-sided 95% lower bound on precision to reach 0.9. With every day
an error that bound is 0.05^(1/n), so it needs 29 clean days. A **dropped-word** pair (`don't` →
`do`, `his` → `history`) never becomes a replacement. "Ordinary" means said at least once per
million words in the bundled subtitle frequency list, `data/words.txt.gz`. The derivation is in
`docs/gate.md` in the repo.
