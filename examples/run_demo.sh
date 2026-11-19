#!/bin/sh
# End-to-end demo on synthetic data. Touches nothing outside a temp folder: Hex data, logs and state all point there.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
S="$HERE/../skills/hex-upsert/scripts"
W=$(mktemp -d)
cp -R "$HERE/hex" "$W/hex"
export HEX_APPLICATION_SUPPORT_DIR="$W/hex" CLAUDE_PROJECTS_DIR="$HERE/claude-projects" HEX_UPSERT_STATE="$W/state"

python3 "$S/collect.py" --days 100000 --out "$W/candidates.json"
python3 "$S/occurrences.py" "$W/candidates.json" --out "$W/labels.json"

# In real use Claude labels each occurrence by reading it. Here the answers come from examples/labels.json.
python3 - "$W/labels.json" "$HERE/labels.json" <<'PY'
import json, sys
sheet, answers = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))
for o in sheet["occurrences"]:
    a = answers[o["heard"]]
    o["label"] = a if isinstance(a, str) else next(v for k, v in a.items() if k.lower() in o["context"].lower())
json.dump(sheet, open(sys.argv[1], "w"), indent=1)
PY

python3 "$S/gate.py" "$W/candidates.json" "$W/labels.json" --out "$W/plan.json"
echo; python3 "$S/upsert.py" "$W/plan.json" --apply
echo; python3 -c "import json,sys; s=json.load(open(sys.argv[1])); print(json.dumps(s['dictation_processing']['default_mode']['replacements'])); print(s['transcription']['recognition_hints'])" "$W/hex/settings.json"
