#!/usr/bin/env python3
"""End-to-end tests on the synthetic examples. Pure Python, so they run the same on macOS,
Linux and Windows (CI runs all three). Touches nothing outside a temp folder.

  python3 tests/run_tests.py

Covers both write paths: Hex 2's direct settings.json write, and Hex 3's `hex` CLI through
tests/fake_hex.py (running and stopped), plus vocabulary, the schema guard and the
SessionStart hook.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = os.path.join(ROOT, "skills", "hex-upsert", "scripts")
EX = os.path.join(ROOT, "examples")
FAKE = os.path.join(ROOT, "tests", "fake_hex.py")
failures = []


def run(script, *args, env, stdin=None, ok=True):
    r = subprocess.run([sys.executable, os.path.join(S, script), *args], env=env, input=stdin,
                       capture_output=True, text=True, encoding="utf-8")
    if ok and r.returncode != 0:
        raise AssertionError(f"{script} {args} exited {r.returncode}\n{r.stdout}\n{r.stderr}")
    return r


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"\n     {detail}"))
    if not cond:
        failures.append(name)


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save(p, obj):
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)


def pipeline(tmp, env):
    """collect -> occurrences -> label from examples/labels.json -> gate. Returns the plan path."""
    cand, labels, plan = (os.path.join(tmp, f) for f in ("candidates.json", "labels.json", "plan.json"))
    run("collect.py", "--days", "100000", "--out", cand, env=env)
    run("occurrences.py", cand, "--out", labels, env=env)
    answers = load(os.path.join(EX, "labels.json"))
    sheet = load(labels)
    for o in sheet["occurrences"]:
        a = answers[o["heard"]]
        o["label"] = a if isinstance(a, str) else next(v for k, v in a.items() if k.lower() in o["context"].lower())
    save(labels, sheet)
    run("gate.py", cand, labels, "--out", plan, env=env)
    return plan


def setup(name, **extra):
    tmp = tempfile.mkdtemp(prefix=f"hexup-{name}-")
    shutil.copytree(os.path.join(EX, "hex"), os.path.join(tmp, "hex"))
    home = os.path.join(tmp, "home")
    os.makedirs(home)
    env = {**os.environ, "HEX_APPLICATION_SUPPORT_DIR": os.path.join(tmp, "hex"),
           "CLAUDE_PROJECTS_DIR": os.path.join(EX, "claude-projects"),
           "HEX_UPSERT_STATE": os.path.join(tmp, "state"), "HOME": home, "USERPROFILE": home,
           "PYTHONIOENCODING": "utf-8", **extra}
    for k in ("HEX_CLI", "HEX_UPSERT_BACKEND", "FAKE_HEX_STOPPED"):
        if k not in extra:
            env.pop(k, None)
    return tmp, env


def replacements(tmp):
    return load(os.path.join(tmp, "hex", "settings.json"))["dictation_processing"]["default_mode"]["replacements"]


def test_gate():
    tmp, env = setup("gate")
    plan = load(pipeline(tmp, env))
    got = {r["heard"]: r["decision"] for r in plan["rows"]}
    want = {"pie torch": "replace", "sequel": "in-context only", "verse cell": "not enough evidence",
            "jason": "not enough evidence", "cloud code": "already in Hex"}
    check("gate decisions match the documented demo", got == want, got)
    check("bundled word list loads (jason is a common word, so 2 days aren't enough)",
          next(r for r in plan["rows"] if r["heard"] == "jason")["rare_form"] is False)


def test_file_backend():
    tmp, env = setup("file")
    plan = pipeline(tmp, env)
    out = run("upsert.py", plan, "--apply", env=env).stdout
    reps = replacements(tmp)
    check("Hex 2 path writes the replacement", {"matched_phrase": "pie torch", "output": "PyTorch"} in reps, out)
    check("Hex 2 path keeps a backup", any(".bak-" in f for f in os.listdir(os.path.join(tmp, "hex"))))
    again = run("upsert.py", plan, "--apply", env=env).stdout
    check("re-running changes nothing", "nothing to change" in again, again)


def test_cli_backend(stopped):
    tag = "stopped" if stopped else "running"
    tmp, env = setup("cli-" + tag, HEX_UPSERT_BACKEND="cli", HEX_CLI=FAKE,
                     **({"FAKE_HEX_STOPPED": "1"} if stopped else {}))
    plan = pipeline(tmp, env)
    dry = run("upsert.py", plan, env=env).stdout
    check(f"Hex 3 ({tag}) dry run lists the replacement", '+ replacement  "pie torch"' in dry, dry)
    out = run("upsert.py", plan, "--apply", env=env).stdout
    reps = replacements(tmp)
    check(f"Hex 3 ({tag}) writes through the CLI",
          {"matched_phrase": "pie torch", "output": "PyTorch"} in reps and
          {"matched_phrase": "cloud code", "output": "Claude Code"} in reps, out)
    backups = os.listdir(os.path.join(tmp, "state", "backups"))
    check(f"Hex 3 ({tag}) saves the old Global mode", len(backups) == 1, backups)
    mode = load(os.path.join(tmp, "hex", "settings.json"))["dictation_processing"]["default_mode"]
    check(f"Hex 3 ({tag}) leaves the mode's other fields alone", mode.get("name") == "Global", mode)


def test_vocabulary():
    tmp, env = setup("vocab", HEX_UPSERT_BACKEND="cli", HEX_CLI=FAKE)
    plan = pipeline(tmp, env)
    out = run("upsert.py", plan, "--apply", "--hints", env=env).stdout
    vocab = load(os.path.join(tmp, "hex", "settings.json")).get("vocabulary", [])
    terms = {v["term"]: v.get("sounds_like", []) for v in vocab}
    check("Hex 3 --hints adds vocabulary with sounds-like spellings",
          terms.get("PyTorch") == ["pie torch"], (terms, out))
    again = run("upsert.py", plan, "--hints", env=env).stdout
    check("vocabulary already present isn't proposed again", "+ vocabulary" not in again, again)


def test_schema_guard():
    for backend, extra in (("file", {}), ("cli", {"HEX_UPSERT_BACKEND": "cli", "HEX_CLI": FAKE})):
        tmp, env = setup("guard-" + backend, **extra)
        plan = pipeline(tmp, env)
        p = os.path.join(tmp, "hex", "settings.json")
        s = load(p)
        s["dictation_processing"]["default_mode"]["replacements"] = [{"pattern": "x", "output": "y"}]
        save(p, s)
        r = run("upsert.py", plan, "--apply", env=env, ok=False)
        check(f"schema guard refuses a reshaped settings file ({backend})",
              r.returncode != 0 and "Nothing was written" in r.stderr and load(p) == s, r.stderr)


def test_no_cli():
    tmp, env = setup("nocli", HEX_UPSERT_BACKEND="cli", HEX_CLI=os.path.join(tmp_missing := tempfile.mkdtemp(), "hex"))
    plan = pipeline(tmp, env)
    r = run("upsert.py", plan, "--apply", env={**env, "FAKE_HEX_STOPPED": "1"}, ok=False)
    check("a missing hex CLI fails cleanly", r.returncode != 0 and "Traceback" not in r.stderr, r.stderr)
    shutil.rmtree(tmp_missing)


def test_hook():
    tmp, env = setup("hook")
    r = run("session_start.py", env=env, stdin=json.dumps({"source": "startup"}))
    check("hook prints the tag rule for a new user", "[heard:" in r.stdout, r.stdout + r.stderr)
    check("hook nudges when a pair has 2+ days of new evidence", "misheard pair" in r.stdout, r.stdout)
    r2 = run("session_start.py", env=env, stdin=json.dumps({"source": "startup"}))
    check("hook nudges at most once a week", "misheard pair" not in r2.stdout, r2.stdout)
    tmp2, env2 = setup("hook-nohex")
    shutil.rmtree(os.path.join(tmp2, "hex"))
    r3 = run("session_start.py", env=env2, stdin="{}")
    check("hook is silent without Hex", r3.stdout == "" and r3.returncode == 0, r3.stdout + r3.stderr)


if __name__ == "__main__":
    test_gate()
    test_file_backend()
    test_cli_backend(stopped=False)
    test_cli_backend(stopped=True)
    test_vocabulary()
    test_schema_guard()
    test_no_cli()
    test_hook()
    print(f"\n{'all passed' if not failures else f'{len(failures)} failed'}")
    sys.exit(1 if failures else 0)
