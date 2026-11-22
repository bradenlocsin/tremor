"""Keep a subscription history backfill going across usage windows (ADR-0027, ADR-0029).

`--engine codex` (default) refines newest-first with Codex CLI; `--engine agy` refines
oldest-first with Gemini on Antigravity CLI, so two supervisors can run at once and meet in the
middle. Each engine has its own log and stop file: data/<engine>-supervisor.{log,stop}.

Runs `tremor refine --backfill --engine codex` until no Candidates are left. When Codex hits its
usage limit (the refine command exits 75), the supervisor waits, checking Codex every 15 minutes
so it resumes as soon as the limit clears, including right after the author applies a manual
reset. It sends a phone alert when the limit looks like the weekly one (the reset is more than
6 hours away), and when the backfill finishes or stalls.

Alerts: iMessage to TREMOR_NOTIFY_IMESSAGE (needs Messages automation permission, granted once),
and/or ntfy to TREMOR_NOTIFY_NTFY_TOPIC. Both are read from the gitignored .env.

Run (from the repo root):  nohup caffeinate -i uv run python scripts/codex_supervisor.py [--engine agy] &
Stop:                      touch data/<engine>-supervisor.stop
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.request import Request, urlopen

REPO = Path(__file__).resolve().parents[1]
ENGINE = "agy" if "--engine" in sys.argv and sys.argv[sys.argv.index("--engine") + 1] == "agy" \
    else "codex"
REGION = sys.argv[sys.argv.index("--region") + 1] if "--region" in sys.argv else "red_sea"
_TAG = ENGINE if REGION == "red_sea" else f"{ENGINE}-{REGION}"
LOG = REPO / "data" / f"{_TAG}-supervisor.log"
STOP = REPO / "data" / f"{_TAG}-supervisor.stop"
AGY_MODEL = "gemini-3.8-flash-medium"  # best precision/recall/speed balance on the Eval set
REFINE = ["uv", "run", "tremor", "refine", "--backfill", "--engine", ENGINE, "--workers", "6",
          "--region", REGION] + (
    ["--model", AGY_MODEL, "--oldest-first"] if ENGINE == "agy" else [])
POLL = 15 * 60
WEEKLY_AFTER = timedelta(hours=6)

sys.path.insert(0, str(REPO / "src"))
from tremor.config import load_config, load_dotenv  # noqa: E402


def log(msg: str) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    with LOG.open("a") as f:
        f.write(line + "\n")


def notify(msg: str) -> None:
    sent = False
    who = os.environ.get("TREMOR_NOTIFY_IMESSAGE")
    if who:
        script = ('on run argv\ntell application "Messages"\n'
                  'set s to 1st account whose service type = iMessage\n'
                  'send (item 1 of argv) to participant (item 2 of argv) of s\n'
                  'end tell\nend run')
        try:
            r = subprocess.run(["osascript", "-e", script, msg, who], capture_output=True,
                               text=True, timeout=150)
            sent = r.returncode == 0
            if not sent:
                log(f"iMessage failed: {r.stderr.strip()[:200]}")
        except subprocess.TimeoutExpired:
            log("iMessage timed out (Messages automation permission not granted yet?)")
    topic = os.environ.get("TREMOR_NOTIFY_NTFY_TOPIC")
    if topic:
        try:
            urlopen(Request(f"https://ntfy.sh/{topic}", data=msg.encode(), method="POST",
                            headers={"Title": "TREMOR"}), timeout=30)
            sent = True
        except OSError as e:
            log(f"ntfy failed: {e}")
    log(f"alert {'sent' if sent else 'NOT sent'}: {msg}")


def remaining() -> int:
    from tremor.refine import pick_candidates
    from tremor.storage import connect
    from tremor.taxonomy import default_taxonomy

    conn = connect(load_config().storage_path)
    tax = default_taxonomy().first_slice()
    n = len(pick_candidates(conn, REGION, 3, taxonomy_version=tax.version))
    conn.close()
    return n


def codex_ok() -> bool:
    """Is the engine usable again? One tiny prompt."""
    if ENGINE == "agy":
        r = subprocess.run(["agy", "-p", "Reply with: ok", "--model", AGY_MODEL,
                            "--print-timeout", "120s"], stdin=subprocess.DEVNULL, cwd="/tmp",
                           capture_output=True, text=True, timeout=300)
        return r.returncode == 0 and "ok" in r.stdout.lower()
    r = subprocess.run(["codex", "exec", "-m", "gpt-6.2-sol", "-s", "read-only", "--ephemeral",
                        "--skip-git-repo-check", "-C", "/tmp", "-"], input="Reply with: ok",
                       capture_output=True, text=True, timeout=300)
    return r.returncode == 0


def reset_time(message: str, now: datetime) -> datetime | None:
    """Parse 'try again at 2:44 PM' or 'try again on Nov 24th, 2026 9:00 AM' style messages."""
    t = re.search(r"(\d{1,2}):(\d{2})\s*([AP]M)", message, re.I)
    if not t:
        return None
    hour = int(t.group(1)) % 12 + (12 if t.group(3).upper() == "PM" else 0)
    when = now.replace(hour=hour, minute=int(t.group(2)), second=0, microsecond=0)
    d = re.search(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})",
                  message)
    if d:
        month = datetime.strptime(d.group(1), "%b").month
        when = when.replace(month=month, day=int(d.group(2)))
        if when < now - timedelta(days=1):
            when = when.replace(year=when.year + 1)
    elif when <= now:
        when += timedelta(days=1)
    return when


def main() -> int:
    load_dotenv()
    os.chdir(REPO)
    log(f"{ENGINE} supervisor started (pid {os.getpid()}); {remaining()} Candidates to refine")
    stalls = 0
    weekly_alerted = False
    queued = False
    while not STOP.exists():
        before = remaining()
        if before == 0 and REGION != "red_sea":  # the Jev queue/features steps are Red Sea only
            notify(f"TREMOR: the {REGION} top-3 refinement is finished ({ENGINE} saw none left).")
            return 0
        if before == 0 and not queued and os.environ.get("TYPESAFE_API_KEY"):
            # Main backfill done: queue Jev-flagged possible Episode starts once (ADR-0031)
            q = subprocess.run(["uv", "run", "tremor", "jev", "queue"], capture_output=True,
                               text=True, check=False)
            log(f"jev queue: {(q.stdout or q.stderr).strip()[-200:]}")
            queued = True
            before = remaining()
            if before:
                notify(f"TREMOR: main backfill done. Jev flagged {before} more articles that "
                       "could start new Episodes; refining those next.")
        if before == 0:
            if os.environ.get("TYPESAFE_API_KEY"):  # features for Events added since (ADR-0031)
                f = subprocess.run(["uv", "run", "tremor", "jev", "features"],
                                   capture_output=True, text=True, check=False)
                log(f"jev features: {(f.stdout or f.stderr).strip()[-200:]}")
            notify(f"TREMOR: the history refinement is finished ({ENGINE} saw none left). "
                   "Every Candidate is refined and has Jev features; next: the final audit, then "
                   "`tremor shocks --final`, `tremor recommend` and `tremor backtest`.")
            return 0
        log(f"starting refine ({before} left)")
        with LOG.open("a") as f:
            proc = subprocess.run(REFINE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True)
            f.write(proc.stdout)
        after = remaining()
        log(f"refine exited {proc.returncode}; {before - after} done this run, {after} left")
        if proc.returncode == 75:
            stalls = 0
            msg = next((x for x in proc.stdout.splitlines() if x.startswith("CODEX_LIMIT")), "")
            now = datetime.now()
            when = reset_time(msg, now)
            log(f"usage limit: {msg} (resets {when or 'unknown'})")
            if ENGINE == "agy" and not weekly_alerted:
                notify(f"TREMOR: Gemini (Antigravity) hit a usage limit; {after} articles left. "
                       "It retries every 15 minutes, nothing to do.")
                weekly_alerted = True
            elif when and when - now > WEEKLY_AFTER and not weekly_alerted:
                notify(f"TREMOR: Codex hit its WEEKLY limit (resets {when:%a %b %-d %-I:%M %p}). "
                       f"{after} articles left. If you want it to keep going now, use one of "
                       "your weekly resets; the backfill resumes within 15 minutes.")
                weekly_alerted = True
            while not STOP.exists():
                time.sleep(POLL)
                if codex_ok():
                    log("Codex is available again")
                    weekly_alerted = False
                    break
            continue
        if before - after == 0:
            stalls += 1
            if stalls >= 3:
                notify(f"TREMOR: the {ENGINE} backfill stopped making progress ({after} left, last "
                       f"exit {proc.returncode}). Check data/codex-supervisor.log.")
                return 1
            time.sleep(60)
        else:
            stalls = 0
    log("stop file found; exiting")
    return 0


if __name__ == "__main__":
    sys.exit(main())
