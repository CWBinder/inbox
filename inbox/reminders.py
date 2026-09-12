"""Reminders: at time T, poke the person with text X on channel C.

A reminder is not a task. It is one JSON file in ~/.pa/reminders/. It may
carry refs, kind-prefixed strings that point at whatever the reminder is
about (ws:task:x, email:work:<id>, whatsapp:Alice:<id>, file:~/x.pdf, url:...).
pa stores refs, prints them into the message, and follows a kind only when
the matching tool is installed.

When the ws store is installed, its tasks with a due date are a second feed
into the same loop. Read only; the one write, marking a task done after a
reply, goes through `ws edit`.
"""
import json
import secrets
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

from . import config, connectors, log, paths, policy, when

STATUSES = ("pending", "sent", "done", "snoozed")


@dataclass
class Reminder:
    id: str
    text: str
    due: str                     # ISO 8601 with offset
    channel: str = "whatsapp"
    status: str = "pending"
    refs: list[str] = field(default_factory=list)
    source: str = "manual"       # manual | ws
    created: str = ""
    sent_at: str | None = None
    note: str = ""

    @property
    def due_dt(self) -> datetime:
        return datetime.fromisoformat(self.due).astimezone()

    @property
    def path(self):
        return paths.REMINDERS / f"{self.id}.json"

    def save(self) -> None:
        paths.REMINDERS.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _now() -> datetime:
    return datetime.now().astimezone()


def _new_id() -> str:
    return "r_" + secrets.token_hex(3)


# ---- own store ---------------------------------------------------------------

def all_reminders() -> list[Reminder]:
    if not paths.REMINDERS.is_dir():
        return []
    out = []
    for f in sorted(paths.REMINDERS.glob("*.json")):
        try:
            out.append(Reminder(**json.loads(f.read_text(encoding="utf-8"))))
        except (json.JSONDecodeError, TypeError):
            continue
    return sorted(out, key=lambda r: r.due)


def get(rid: str) -> Reminder:
    for r in all_reminders():
        if r.id == rid:
            return r
    raise SystemExit(f"no reminder '{rid}' (inbox remind list --all shows ids)")


def add(text: str, due: datetime, refs: list[str], channel: str = "whatsapp") -> Reminder:
    r = Reminder(id=_new_id(), text=text, due=due.isoformat(timespec="minutes"), channel=channel,
                 refs=list(refs), created=_now().isoformat(timespec="seconds"))
    r.save()
    return r


# ---- ws feed -----------------------------------------------------------------

def ws_due_tasks(within: timedelta | None = None) -> list[Reminder]:
    """Open ws tasks whose due date has arrived (or arrives within `within`),
    as synthetic reminders with a ws: ref. Empty when ws is not installed."""
    if not shutil.which("ws"):
        return []
    try:
        listed = json.loads(subprocess.run(["ws", "list", "tasks", "--json"], capture_output=True, text=True, check=True).stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return []
    horizon = _now() + (within or timedelta(0))
    out = []
    for item in listed:
        if item.get("status") in ("done", "closed", "cancelled"):
            continue
        try:
            rec = json.loads(subprocess.run(["ws", "show", item["ref"], "--json"], capture_output=True, text=True, check=True).stdout)
        except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError):
            continue
        due = rec.get("due")
        if not due:
            continue
        due_dt = when.parse(str(due))
        if due_dt <= horizon:
            out.append(Reminder(id="ws:" + item["ref"].split(":", 1)[1], text=rec.get("name", item["ref"]),
                                due=due_dt.isoformat(timespec="minutes"), refs=["ws:" + item["ref"]], source="ws",
                                status="pending"))
    return out


def _ws_sent() -> dict:
    f = paths.STATE / "ws-sent.json"
    return json.loads(f.read_text()) if f.is_file() else {}


def _mark_ws_sent(ref: str, due: str) -> None:
    paths.STATE.mkdir(parents=True, exist_ok=True)
    d = _ws_sent()
    d[ref] = due
    (paths.STATE / "ws-sent.json").write_text(json.dumps(d, indent=2) + "\n")


# ---- rendering and sending ---------------------------------------------------

def render(r: Reminder) -> str:
    lines = [f"Reminder: {r.text}", f"Due {when.fmt(r.due_dt)}"]
    for ref in r.refs:
        kind, _, rest = ref.partition(":")
        if kind == "url":
            lines.append(rest)
        elif kind == "ws":
            lines.append(f"ws show {rest}")
        else:
            lines.append(ref)
    lines.append(f"Reply 'done {r.id}' or 'snooze {r.id} 2h'.")
    return "\n".join(lines)


def send(r: Reminder, dry_run: bool = False) -> tuple[bool, str]:
    """A reminder goes out from the [reminders].via channel to the [reminders].to
    channel's address, so it arrives from a second number and the phone notifies."""
    via, to = config.reminders_via(), config.reminders_to()
    if to.connector == via.connector and to.address:
        recipient = to.address
    else:
        res = connectors.resolve(via, to.name)                 # e.g. "me" as the telegram bot knows it
        if not res:
            return False, f"'{to.name}' is not a known contact on channel '{via.name}' ({via.connector})"
        recipient = res["address"]
    verdict = policy.send(via, recipient, confirmed=False)
    if not verdict.allowed:
        return False, verdict.reason
    body = render(r)
    if dry_run:
        return True, f"DRY RUN via {via.name} -> {to.name} ({recipient}):\n{body}"
    ok, res, err, _ = connectors.run(via, "send", recipient, "--body", body, env=connectors.send_env(via.connector))
    out = json.dumps(res) if res else err
    log.record("remind", channel=via.name, recipient=recipient, ok=ok, detail=r.text[:200], result=out[:200], reminder=r.id)
    return ok, out


def run(dry_run: bool = False) -> list[str]:
    """Fire everything due. Returns one report line per reminder considered."""
    now = _now()
    report = []
    for r in all_reminders():
        if r.status not in ("pending", "snoozed") or r.due_dt > now:
            continue
        ok, msg = send(r, dry_run)
        if ok and not dry_run:
            r.status, r.sent_at = "sent", now.isoformat(timespec="seconds")
            r.save()
        report.append(f"{'sent' if ok else 'FAILED'} {r.id}  {r.text}" + ("" if ok else f"  ({msg})") + (f"\n{msg}" if dry_run else ""))
    sent = _ws_sent()
    for r in ws_due_tasks():
        ref = r.refs[0][3:]                       # bare ws REF, task:<key>
        if sent.get(ref) == r.due:
            continue
        ok, msg = send(r, dry_run)
        if ok and not dry_run:
            _mark_ws_sent(ref, r.due)
        report.append(f"{'sent' if ok else 'FAILED'} {r.id}  {r.text}" + ("" if ok else f"  ({msg})") + (f"\n{msg}" if dry_run else ""))
    return report


def mark_done(rid: str) -> str:
    if rid.startswith("ws:"):
        ref = "task:" + rid[3:]
        if not shutil.which("ws"):
            raise SystemExit("ws is not installed; cannot mark a ws task")
        subprocess.run(["ws", "edit", ref, "--status", "done"], check=True)
        log.record("task-done", channel="ws", ok=True, detail=ref)
        return f"{ref} marked done in ws"
    r = get(rid)
    r.status = "done"
    r.save()
    return f"{rid} done"


def snooze(rid: str, until: datetime) -> str:
    if rid.startswith("ws:"):
        raise SystemExit("snoozing a ws task means changing its due date: ws edit task:<key> --due YYYY-MM-DD")
    r = get(rid)
    r.status, r.due = "snoozed", until.isoformat(timespec="minutes")
    r.save()
    return f"{rid} snoozed until {when.fmt(until)}"


# ---- launchd timer -----------------------------------------------------------

LAUNCHD_LABEL = "inbox.remind"
PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{label}</string>
  <key>ProgramArguments</key><array><string>{pa}</string><string>remind</string><string>run</string></array>
  <key>StartInterval</key><integer>{seconds}</integer>
  <key>RunAtLoad</key><true/>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>{path}</string></dict>
  <key>StandardOutPath</key><string>{log}</string>
  <key>StandardErrorPath</key><string>{log}</string>
</dict></plist>
"""


def _plist_path():
    from pathlib import Path
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


def install_timer(every_minutes: int) -> str:
    import os
    plist = _plist_path()
    plist.parent.mkdir(parents=True, exist_ok=True)
    paths.LOG.mkdir(parents=True, exist_ok=True)
    pa_bin = shutil.which("inbox")
    if not pa_bin:
        raise SystemExit("inbox is not on PATH")
    plist.write_text(PLIST.format(label=LAUNCHD_LABEL, pa=pa_bin, seconds=every_minutes * 60,
                                  path=os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
                                  log=paths.LOG / "remind-run.log"))
    subprocess.run(["launchctl", "unload", str(plist)], capture_output=True)
    subprocess.run(["launchctl", "load", str(plist)], check=True)
    return f"installed {plist}: `inbox remind run` every {every_minutes} min, log in {paths.LOG / 'remind-run.log'}"


def uninstall_timer() -> str:
    plist = _plist_path()
    if not plist.is_file():
        return "no timer installed"
    subprocess.run(["launchctl", "unload", str(plist)], capture_output=True)
    plist.unlink()
    return "timer removed"


def timer_installed() -> bool:
    return _plist_path().is_file()
