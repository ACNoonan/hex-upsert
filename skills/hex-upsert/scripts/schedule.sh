#!/bin/sh
# Install, update or remove the weekly unattended run (macOS launchd, Sundays 04:00).
#
#   schedule.sh                 weekly check; notifies you when safe corrections are ready
#   schedule.sh --auto-apply    weekly check that also applies them, then notifies you
#   schedule.sh --store-token   run `claude setup-token` and keep the token in your Keychain, so the
#                               job keeps working when your normal `claude` login expires
#   schedule.sh --uninstall     remove the job (and the Keychain token)
#
# launchd jobs can't read ~/Documents (macOS privacy protection), so the scripts are copied to
# ~/Library/Application Support/hex-upsert/bin and run from there. Re-run after updating.
set -e
if [ "$(uname)" != "Darwin" ]; then
  # Linux (systemd user timer) and Windows (Task Scheduler) live in schedule.py
  exec python3 "$(dirname "$0")/schedule.py" "$@"
fi
HERE=$(cd "$(dirname "$0")" && pwd)
STATE="$HOME/Library/Application Support/hex-upsert"
LABEL=local.hex-upsert
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

remove() {
  launchctl bootout "$DOMAIN/$1" 2>/dev/null || true
  rm -f "$HOME/Library/LaunchAgents/$1.plist"
}

KC_SERVICE=hex-upsert
KC_ACCOUNT=claude-oauth-token
has_token() { security find-generic-password -s "$KC_SERVICE" -a "$KC_ACCOUNT" >/dev/null 2>&1; }

if [ "$1" = "--uninstall" ]; then
  remove "$LABEL"
  rm -f "$STATE/scheduled"
  security delete-generic-password -s "$KC_SERVICE" -a "$KC_ACCOUNT" >/dev/null 2>&1 || true
  echo "removed the weekly hex-upsert job and its Keychain token"
  exit 0
fi

CLAUDE=$(command -v claude || echo "$HOME/.local/bin/claude")
if [ ! -x "$CLAUDE" ]; then
  echo "claude CLI not found on PATH or at ~/.local/bin/claude. Nothing installed." >&2
  exit 1
fi

if [ "$1" = "--store-token" ]; then
  echo "Step 1 of 2: claude setup-token opens your browser and prints a long-lived token (sk-ant-oat...)."
  "$CLAUDE" setup-token
  printf "Step 2 of 2: paste that token here (input hidden): "
  stty -echo; read -r TOKEN; stty echo; echo
  case "$TOKEN" in
    sk-ant-oat*) ;;
    *) echo "That isn't a setup-token (they start sk-ant-oat). Nothing stored." >&2; exit 1 ;;
  esac
  # one tiny call on the subscription to prove the token works before storing it
  if ! env -u ANTHROPIC_API_KEY -u ANTHROPIC_AUTH_TOKEN CLAUDE_CODE_OAUTH_TOKEN="$TOKEN" \
       "$CLAUDE" -p "Reply with the word ok" --tools "" --model haiku --no-session-persistence >/dev/null 2>&1; then
    echo "claude -p failed with that token. Nothing stored." >&2; exit 1
  fi
  security add-generic-password -U -s "$KC_SERVICE" -a "$KC_ACCOUNT" -l "hex-upsert: Claude setup-token" -w "$TOKEN"
  TOKEN=""
  echo "Stored in your login Keychain (service $KC_SERVICE). The weekly job uses it from the next run; no reinstall needed."
  exit 0
fi
AUTO=""
[ "$1" = "--auto-apply" ] && AUTO="<string>--auto-apply</string>"

# Hex 3 keeps its settings in .../hex, Hex 2 in .../voice-control. Hex 1 used a format this tool doesn't write.
AS="$HOME/Library/Application Support"
if [ ! -f "$AS/hex/settings.json" ] && [ ! -f "$AS/voice-control/settings.json" ]; then
  echo "No Hex settings found in ~/Library/Application Support/hex (Hex 3) or .../voice-control (Hex 2)." >&2
  echo "Install Hex from https://anoma.ly/hex and run it once. Nothing installed." >&2
  exit 1
fi

# The weekly run labels with headless `claude -p` and strips API keys from its environment, so it
# only ever runs on a Claude subscription: a `claude` login, or a setup-token in the Keychain.
METHOD=$(env -u ANTHROPIC_API_KEY -u ANTHROPIC_AUTH_TOKEN "$CLAUDE" auth status --json 2>/dev/null \
  | /usr/bin/python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("authMethod","") if d.get("loggedIn") else "")' 2>/dev/null || true)
if [ "$METHOD" != "claude.ai" ] && ! has_token; then
  echo "The weekly run needs a Claude subscription login (claude auth login), so it never bills an API key." >&2
  echo "Found auth method: '${METHOD:-none}'. Nothing installed." >&2
  exit 1
fi
CLAUDE_DIR=$(dirname "$CLAUDE")

mkdir -p "$STATE/bin" "$STATE/data" "$HOME/Library/LaunchAgents"
cp "$HERE"/*.py "$STATE/bin/"
cp "$HERE"/../data/* "$STATE/data/"
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
date +%s > "$STATE/scheduled"
if [ -n "$AUTO" ]; then MODE="applies safe corrections, then notifies you"; else MODE="notifies you when safe corrections are ready"; fi
echo "installed $LABEL: Sundays 04:00, $MODE. Log: ~/Library/Logs/hex-upsert.log"
