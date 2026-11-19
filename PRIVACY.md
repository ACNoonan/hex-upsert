# Privacy

hex-upsert runs on your computer. It has no server, no account, no analytics and no telemetry,
and its author receives nothing from it.

## What it reads

- Your Claude Code session logs in `~/.claude/projects/`, from the last 60 days. It keeps only
  the `[heard: "X" → meant: "Y"]` tags Claude wrote, and discards the rest.
- Hex's `history.json`, the transcripts Hex already keeps on your machine.
- Hex's settings, to see which replacements and vocabulary terms already exist.

## What leaves your computer

One thing: to decide whether a mishearing is real, Claude reads a snippet of about 140
characters around each match in your Hex history. That goes to Anthropic through your own
Claude Code session, or through headless `claude -p` if you install the weekly job. That is
ordinary Claude Code use, under the same terms as the rest of your sessions. Nothing is sent
anywhere else.

## What it writes

- Hex's Global replacements and Vocabulary, after you say yes, or without asking if you
  installed the weekly job with `--auto-apply`. Every change has a backup and can be undone
  with `/hex-upsert:hex-upsert undo`.
- Its own working files, in a `hex-upsert` folder beside Hex's data folder.
- A weekly scheduled job, only if you run `schedule`. On macOS, `schedule.sh --store-token`
  also stores a Claude subscription token in your login Keychain. `--uninstall` removes both.

## Removing it

Uninstall the plugin in Claude Code, run the installer with `--uninstall` if you set up the
weekly job, and delete the `hex-upsert` folder. Replacements already in Hex stay until you
remove them in Hex or with `undo`.

Questions: open an issue at <https://github.com/ACNoonan/hex-upsert/issues>.
