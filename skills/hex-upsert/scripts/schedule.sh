#!/bin/sh
# Install, update or remove the weekly unattended run (macOS launchd, Sundays 04:00).
#
#   schedule.sh                 weekly check; notifies you when safe corrections are ready
#   schedule.sh --auto-apply    weekly check that also applies them, then notifies you
#   schedule.sh --uninstall     remove the job
#
# launchd jobs can't read ~/Documents (macOS privacy protection), so the scripts are copied to
# ~/Library/Application Support/hex-upsert/bin and run from there. Re-run after updating.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
STATE="$HOME/Library/Application Support/hex-upsert"
LABEL=local.hex-upsert
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

remove() {
  launchctl bootout "$DOMAIN/$1" 2>/dev/null || true
  rm -f "$HOME/Library/LaunchAgents/$1.plist"
}

if [ "$1" = "--uninstall" ]; then
  remove "$LABEL"
  echo "removed the weekly hex-upsert job"
  exit 0
fi
AUTO=""
[ "$1" = "--auto-apply" ] && AUTO="<string>--auto-apply</string>"

# Hex 2 keeps its settings here. Hex 1 used a different format that this tool doesn't write.
if [ ! -f "$HOME/Library/Application Support/voice-control/settings.json" ]; then
  echo "Hex 2 settings not found at ~/Library/Application Support/voice-control/settings.json." >&2
  echo "hex-upsert needs Hex 2 (com.kitlangton.hex2). Nothing installed." >&2
  exit 1
fi

# The weekly run labels with headless `claude -p` and strips API keys from its environment, so it
# only ever runs on a Claude subscription login. Check that login exists before installing.
CLAUDE=$(command -v claude || echo "$HOME/.local/bin/claude")
if [ ! -x "$CLAUDE" ]; then
  echo "claude CLI not found on PATH or at ~/.local/bin/claude. Nothing installed." >&2
  exit 1
fi
METHOD=$(env -u ANTHROPIC_API_KEY -u ANTHROPIC_AUTH_TOKEN "$CLAUDE" auth status --json 2>/dev/null \
  | /usr/bin/python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("authMethod","") if d.get("loggedIn") else "")' 2>/dev/null || true)
if [ "$METHOD" != "claude.ai" ]; then
  echo "The weekly run needs a Claude subscription login (claude auth login), so it never bills an API key." >&2
  echo "Found auth method: '${METHOD:-none}'. Nothing installed." >&2
  exit 1
fi
CLAUDE_DIR=$(dirname "$CLAUDE")

mkdir -p "$STATE/bin" "$HOME/Library/LaunchAgents"
cp "$HERE"/*.py "$STATE/bin/"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/caffeinate</string><string>-i</string>
    <string>/usr/bin/python3</string><string>$STATE/bin/run_weekly.py</string>
    $AUTO
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>$CLAUDE_DIR:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    <key>CLAUDE_BIN</key><string>$CLAUDE</string>
  </dict>
  <key>StartCalendarInterval</key>
  <dict><key>Weekday</key><integer>0</integer><key>Hour</key><integer>4</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/hex-upsert.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/hex-upsert.log</string>
</dict>
</plist>
PL
plutil -lint "$PLIST" >/dev/null
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST"
if [ -n "$AUTO" ]; then MODE="applies safe corrections, then notifies you"; else MODE="notifies you when safe corrections are ready"; fi
echo "installed $LABEL: Sundays 04:00, $MODE. Log: ~/Library/Logs/hex-upsert.log"
