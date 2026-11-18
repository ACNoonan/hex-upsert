#!/usr/bin/env python3
"""Install, update or remove the weekly unattended run on Linux (systemd user timer) or Windows
(Task Scheduler), Sundays 04:00. macOS uses schedule.sh (launchd).

  schedule.py                 weekly check; notifies you when safe corrections are ready
  schedule.py --auto-apply    weekly check that also applies them, then notifies you
  schedule.py --uninstall     remove the job
  schedule.py --dry-run       print what would be installed, change nothing

The scripts are copied to <state>/bin and <state>/data and run from there, so a plugin update
can't break a scheduled run halfway. Re-run after updating.

The run labels with headless `claude -p` on the user's Claude subscription and strips API keys,
so this refuses to install unless `claude auth status` shows a claude.ai login. A missed run
(machine off or asleep at 04:00) runs at the next chance: Persistent=true on systemd,
StartWhenAvailable on Windows.
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from hexpaths import STATE, SYSTEM, hex_installed, write_text  # noqa: E402

NAME = "hex-upsert"
LOG = os.path.join(STATE, "hex-upsert.log")
UNIT_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "systemd", "user")


def claude_bin():
    return shutil.which("claude") or os.path.expanduser(os.path.join("~", ".local", "bin", "claude"))


def auth_method(claude):
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
    try:
        r = subprocess.run([claude, "auth", "status", "--json"], capture_output=True, text=True,
                           encoding="utf-8", env=env, timeout=30)
        d = json.loads(r.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return ""
    return d.get("authMethod", "") if d.get("loggedIn") else ""


# ---- Linux: systemd user timer --------------------------------------------------------------

def systemd_units(python, claude, auto):
    args = " --auto-apply" if auto else ""
    path = os.pathsep.join([os.path.dirname(claude), os.path.expanduser("~/.local/bin"),
                            "/usr/local/bin", "/usr/bin", "/bin"])
    service = f"""[Unit]
Description=hex-upsert: turn safe dictation corrections into Hex replacements

[Service]
Type=oneshot
ExecStart="{python}" "{os.path.join(STATE, 'bin', 'run_weekly.py')}"{args}
Environment="PATH={path}"
Environment="CLAUDE_BIN={claude}"
StandardOutput=append:{LOG}
StandardError=append:{LOG}
Nice=10
"""
    timer = """[Unit]
Description=hex-upsert weekly run (Sundays 04:00)

[Timer]
OnCalendar=Sun *-*-* 04:00:00
Persistent=true
RandomizedDelaySec=10min

[Install]
WantedBy=timers.target
"""
    return {f"{NAME}.service": service, f"{NAME}.timer": timer}


def systemctl(*args):
    r = subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"systemctl --user {' '.join(args)} failed: {r.stderr.strip()}")


def install_linux(units):
    os.makedirs(UNIT_DIR, exist_ok=True)
    for name, text in units.items():
        write_text(os.path.join(UNIT_DIR, name), text)
    systemctl("daemon-reload")
    systemctl("enable", "--now", f"{NAME}.timer")


def uninstall_linux():
    subprocess.run(["systemctl", "--user", "disable", "--now", f"{NAME}.timer"], capture_output=True)
    for name in (f"{NAME}.service", f"{NAME}.timer"):
        p = os.path.join(UNIT_DIR, name)
        if os.path.exists(p):
            os.remove(p)
    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)


# ---- Windows: Task Scheduler ----------------------------------------------------------------

def ps_quote(s):
    return "'" + s.replace("'", "''") + "'"


def windows_task(python, claude, auto):
    """A .cmd wrapper (sets the environment, appends to the log) and the PowerShell that registers it."""
    wrapper = os.path.join(STATE, "bin", "run_weekly.cmd")
    cmd = ("@echo off\r\n"
           "chcp 65001 >nul\r\n"
           f'set "CLAUDE_BIN={claude}"\r\n'
           f'set "PATH={os.path.dirname(claude)};%PATH%"\r\n'
           "set PYTHONIOENCODING=utf-8\r\n"
           f'"{python}" "{os.path.join(STATE, "bin", "run_weekly.py")}"{" --auto-apply" if auto else ""}'
           f' >> "{LOG}" 2>&1\r\n')
    argument = ps_quote('/c "' + wrapper + '"')
    ps = (f"$a = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument {argument};"
          "$t = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 4am;"
          "$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries "
          "-DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 2);"
          f"Register-ScheduledTask -TaskName {ps_quote(NAME)} -Action $a -Trigger $t -Settings $s "
          "-Description 'hex-upsert weekly run' -Force | Out-Null")
    return wrapper, cmd, ps


def powershell(script):
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"PowerShell failed: {r.stderr.strip()[:500]}")


def uninstall_windows():
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                    f"Unregister-ScheduledTask -TaskName {ps_quote(NAME)} -Confirm:$false -ErrorAction SilentlyContinue"],
                   capture_output=True)


# ---- main -----------------------------------------------------------------------------------

def copy_scripts():
    for sub in ("bin", "data"):
        os.makedirs(os.path.join(STATE, sub), exist_ok=True)
    for f in glob.glob(os.path.join(HERE, "*.py")):
        shutil.copy2(f, os.path.join(STATE, "bin"))
    for f in glob.glob(os.path.join(os.path.dirname(HERE), "data", "*")):
        shutil.copy2(f, os.path.join(STATE, "data"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--auto-apply", action="store_true")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="print what would be installed")
    ap.add_argument("--os", choices=["Linux", "Windows"], default=SYSTEM, help=argparse.SUPPRESS)
    a = ap.parse_args()
    target = a.os
    if target == "Darwin":
        sys.exit("On macOS use schedule.sh (launchd).")
    if target not in ("Linux", "Windows"):
        sys.exit(f"No scheduler support for {target}.")

    marker = os.path.join(STATE, "scheduled")
    if a.uninstall:
        if not a.dry_run:
            uninstall_linux() if target == "Linux" else uninstall_windows()
            if os.path.exists(marker):
                os.remove(marker)
        print(f"removed the weekly {NAME} job")
        return

    claude = claude_bin()
    if not a.dry_run and os.environ.get("HEX_UPSERT_SKIP_CHECKS") != "1":  # CI only
        if not hex_installed():
            sys.exit("Hex's settings weren't found. Install Hex from https://anoma.ly/hex and run it once. Nothing installed.")
        if not os.path.exists(claude) and not shutil.which("claude"):
            sys.exit("claude CLI not found on PATH. Nothing installed.")
        method = auth_method(claude)
        if method != "claude.ai":
            sys.exit("The weekly run needs a Claude subscription login (claude auth login), so it never bills an "
                     f"API key. Found auth method: '{method or 'none'}'. Nothing installed.")

    python = sys.executable
    mode = "applies safe corrections, then notifies you" if a.auto_apply else "notifies you when safe corrections are ready"
    if target == "Linux":
        units = systemd_units(python, claude, a.auto_apply)
        if a.dry_run:
            for name, text in units.items():
                print(f"--- {os.path.join(UNIT_DIR, name)}\n{text}")
            return
        copy_scripts()
        install_linux(units)
        where = f"systemd user timer {NAME}.timer (systemctl --user list-timers {NAME}.timer)"
    else:
        wrapper, cmd, ps = windows_task(python, claude, a.auto_apply)
        if a.dry_run:
            print(f"--- {wrapper}\n{cmd}\n--- PowerShell\n{ps}")
            return
        copy_scripts()
        with open(wrapper, "w", encoding="utf-8", newline="") as f:
            f.write(cmd)
        powershell(ps)
        where = f"Task Scheduler task '{NAME}' (Get-ScheduledTask {NAME})"
    write_text(marker, "installed\n")
    print(f"installed {where}: Sundays 04:00, {mode}. Log: {LOG}")
    if target == "Linux":
        print("Note: user timers run only while you're logged in, unless you run `loginctl enable-linger`.")


if __name__ == "__main__":
    main()
