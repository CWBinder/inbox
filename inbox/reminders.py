"""Reminders: one Markdown file each in ~/.inbox/reminders/, a YAML header for
the loop and a brief for the agent. See REMINDERS.md.

The loop (`inbox remind run`, on a timer) is deterministic: it reads the
person's replies on the reminder channel, checks each open reminder's due
time and watches, and tells the person when something happened. Only the
person starts an agent, by replying; the reply is the prompt, the reminder's
role is the persona, the answer goes back to the phone. Every reply of theirs
continues the same session.
"""
import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from . import config, connectors, log, paths, policy, when

STATUSES = ("pending", "told", "done", "snoozed")
HEADER_KEYS = ("id", "due", "status", "role", "session", "mode", "refs", "watch", "created", "told_at", "checked_at")
WATCH_KINDS = ("email:from", "email:thread", "whatsapp:chat", "telegram:chat", "ws")


# ---- the record --------------------------------------------------------------

@dataclass
class Reminder:
    id: str
    title: str
    due: str                                  # "YYYY-MM-DD HH:MM" local, or ISO
    status: str = "pending"
    role: str | None = None                   # a roster role; None means the plain watcher
    session: str | None = None                # claude session id the conversation continues in
    mode: str | None = None                   # "resume" | "fresh": the person's choice, once
    refs: list[str] = field(default_factory=list)
    watch: list[str] = field(default_factory=list)
    created: str = ""
    told_at: str | None = None                # last time the person was told about it
    checked_at: str | None = None             # last watch check
    body: str = ""                            # the brief, Markdown, without the title
    log_lines: list[str] = field(default_factory=list)

    @property
    def due_dt(self) -> datetime:
        return when.parse(self.due)

    @property
    def path(self) -> Path:
        return paths.REMINDERS / f"{self.id}.md"

    @property
    def watches(self) -> list[str]:
        """Explicit watches plus what the refs imply: a message ref watches its thread."""
        out = list(self.watch)
        for ref in self.refs:
            kind, _, rest = ref.partition(":")
            if kind in ("email", "whatsapp", "telegram") and rest.count(":") == 1:
                out.append(f"{kind}:thread:{rest}")
            elif kind == "ws":
                out.append(ref)
        return list(dict.fromkeys(out))

    # -- serialisation ------------------------------------------------------

    def render_file(self) -> str:
        head = [f"id: {self.id}", f"due: {self.due}", f"status: {self.status}"]
        for key in ("role", "session", "mode", "created", "told_at", "checked_at"):
            v = getattr(self, key)
            if v:
                head.append(f"{key}: {v}")
        for key in ("refs", "watch"):
            v = getattr(self, key)
            if v:
                head.append(f"{key}:")
                head += [f"  - {x}" for x in v]
        parts = ["---", *head, "---", "", f"# {self.title}"]
        if self.body.strip():
            parts += ["", self.body.strip()]
        if self.log_lines:
            parts += ["", "## Log", *[f"- {l}" for l in self.log_lines]]
        return "\n".join(parts) + "\n"

    def save(self) -> None:
        paths.REMINDERS.mkdir(parents=True, exist_ok=True)
        self.path.write_text(self.render_file(), encoding="utf-8")

    def note(self, text: str) -> None:
        self.log_lines.append(f"{_now().strftime('%Y-%m-%d %H:%M')}  {text}")


def _parse_header(text: str) -> dict:
    data: dict = {}
    key = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith((" ", "\t")) and line.strip().startswith("- ") and key:
            data.setdefault(key, [])
            if isinstance(data[key], list):
                data[key].append(line.strip()[2:].strip().strip("\"'"))
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if value.startswith("[") and value.endswith("]"):
            data[key] = [v.strip().strip("\"'") for v in value[1:-1].split(",") if v.strip()]
        elif value == "":
            data[key] = []
        else:
            data[key] = value.strip("\"'")
    return data


def parse_file(path: Path) -> "Reminder | None":
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    try:
        _, header, rest = text.split("---", 2)
    except ValueError:
        return None
    h = _parse_header(header)
    if not h.get("id") or not h.get("due"):
        return None
    rest = rest.strip("\n")
    title, body, log_lines = h["id"], "", []
    m = re.match(r"#\s+(.+)\n?", rest)
    if m:
        title, rest = m.group(1).strip(), rest[m.end():]
    if "\n## Log" in "\n" + rest:
        body_part, _, log_part = ("\n" + rest).partition("\n## Log")
        body = body_part.strip("\n")
        log_lines = [l.strip()[2:] for l in log_part.splitlines() if l.strip().startswith("- ")]
    else:
        body = rest.strip("\n")
    return Reminder(id=str(h["id"]), title=title, due=str(h["due"]), status=str(h.get("status", "pending")),
                    role=h.get("role") or None, session=h.get("session") or None, mode=h.get("mode") or None,
                    refs=list(h.get("refs") or []), watch=list(h.get("watch") or []), created=str(h.get("created", "")),
                    told_at=h.get("told_at") or None, checked_at=h.get("checked_at") or None, body=body, log_lines=log_lines)


def _now() -> datetime:
    return datetime.now().astimezone()


def _stamp(dt: datetime | None = None) -> str:
    return (dt or _now()).strftime("%Y-%m-%d %H:%M")


_STOP = {"the", "a", "an", "to", "of", "for", "and", "my", "in", "on", "at", "with", "about"}


def _slug(text: str) -> str:
    """Short id from the first three meaningful words: 'Pay the KITP conference fee' -> 'pay-kitp-conference'."""
    words = [w for w in re.sub(r"[^a-z0-9 ]+", " ", text.lower()).split() if w not in _STOP]
    return "-".join(words[:3]) or "reminder"


# ---- store ---------------------------------------------------------------------

def all_reminders() -> list[Reminder]:
    if not paths.REMINDERS.is_dir():
        return []
    out = []
    for f in sorted(paths.REMINDERS.glob("*.md")):
        r = parse_file(f)
        if r:
            out.append(r)
    return sorted(out, key=lambda r: r.due_dt)


def get(rid: str) -> Reminder:
    for r in all_reminders():
        if r.id == rid:
            return r
    raise SystemExit(f"no reminder '{rid}' (inbox remind list --all shows ids)")


def open_reminders() -> list[Reminder]:
    return [r for r in all_reminders() if r.status in ("pending", "told", "snoozed")]


def add(title: str, due: datetime, refs: list[str], role: str | None = None, watch: list[str] | None = None,
        body: str = "", session: str | None = None, rid: str | None = None) -> Reminder:
    rid = rid or _slug(title)
    if (paths.REMINDERS / f"{rid}.md").exists():
        n = 2
        while (paths.REMINDERS / f"{rid}-{n}.md").exists():
            n += 1
        rid = f"{rid}-{n}"
    r = Reminder(id=rid, title=title, due=_stamp(due), refs=list(refs), role=role, watch=list(watch or []),
                 body=body, session=session, created=_stamp())
    r.note("created")
    r.save()
    return r


TEMPLATE_BODY = """**Goal.** What being done looks like.

**State.** Where it stands now, with dates.

**Waiting for.** What has to happen before the next step.

**Next step.** The one concrete action.

**Agent may.** What the role may do without asking. Sending always needs a yes.

**Done when.** The condition that closes it."""


# ---- watches -------------------------------------------------------------------

def _since_arg(r: Reminder) -> str:
    base = r.checked_at or r.told_at or r.created or _stamp(_now() - timedelta(days=1))
    return base


def check_watches(r: Reminder) -> list[str]:
    """New items since the last check, as one-line descriptions. No agent."""
    since = _since_arg(r)
    hits: list[str] = []
    for w in r.watches:
        kind, _, rest = w.partition(":")
        try:
            if kind == "email" and rest.startswith(("from:", "thread:")):
                sub, _, value = rest.partition(":")
                for ch in _channels_for_kind("gmail"):
                    q = f"from:{value}" if sub == "from" else ""
                    rows = connectors.records(ch, "search", *([q] if q else []), "-n", "10", "--since", since)
                    for m in rows:
                        if sub == "thread":
                            thr, _, mid = value.partition(":")
                            if m.get("thread") != _thread_of(ch, mid) and m.get("id") != mid:
                                continue
                        if m.get("from") == "me":
                            continue
                        hits.append(f"email:{ch.name}:{m['id']}  from {m.get('from_name') or m.get('from')}, \"{m.get('subject','')}\", {m.get('when','')[:16]}: {m.get('text','')[:160]}")
            elif kind in ("whatsapp", "telegram") and rest.startswith(("chat:", "thread:")):
                sub, _, value = rest.partition(":")
                who = value.partition(":")[0] if sub == "thread" else value
                for ch in _channels_for_kind(kind):
                    rows = connectors.records(ch, "search", "--chat", who, "-n", "10", "--since", since) if kind == "whatsapp" \
                        else connectors.records(ch, "search", "-n", "10", "--since", since)
                    for m in rows:
                        if m.get("from") == "me":
                            continue
                        hits.append(f"{kind}:{ch.name}:{m['id']}  {m.get('from_name') or m.get('from')} in {m.get('thread_name') or who}, {m.get('when','')[:16]}: {m.get('text','')[:160]}")
            elif kind == "ws" and shutil.which("ws"):
                res = subprocess.run(["ws", "show", rest, "--json"], capture_output=True, text=True)
                if res.returncode == 0:
                    rec = json.loads(res.stdout)
                    upd = str(rec.get("updated_at", ""))[:16].replace("T", " ")
                    if upd and upd > since:
                        hits.append(f"ws:{rest}  updated {upd}, status {rec.get('status')}")
        except (SystemExit, json.JSONDecodeError, KeyError):
            continue
    return hits


def _thread_of(ch: config.Channel, mid: str) -> str | None:
    ok, rows, _, _ = connectors.run(ch, "read", mid)
    if ok and isinstance(rows, list) and rows:
        return rows[0].get("thread")
    return None


def _channels_for_kind(connector: str) -> list[config.Channel]:
    return [c for c in config.channels().values() if c.connector == connector and c.name != config.reminders_via().name]


# ---- telling the person --------------------------------------------------------

def _recipient() -> tuple[config.Channel, str]:
    via, to = config.reminders_via(), config.reminders_to()
    if to.connector == via.connector and to.address:
        return via, to.address
    res = connectors.resolve(via, to.name)
    if not res:
        raise SystemExit(f"'{to.name}' is not a known contact on channel '{via.name}'")
    return via, res["address"]


def tell(text: str, r: Reminder | None = None, dry_run: bool = False) -> tuple[bool, str]:
    via, recipient = _recipient()
    verdict = policy.send(via, recipient, confirmed=False)
    if not verdict.allowed:
        return False, verdict.reason
    if dry_run:
        return True, f"DRY RUN via {via.name} -> {recipient}:\n{text}"
    ok, res, err, _ = connectors.run(via, "send", recipient, "--body", text, env=connectors.send_env(via.connector))
    log.record("remind", channel=via.name, recipient=recipient, ok=ok, detail=text[:200], reminder=r.id if r else None)
    return ok, (json.dumps(res) if res else err)


def ensure_chat(r: Reminder) -> None:
    """A reminder with a role is a chat of the same name, so `talk ID` works
    the moment it is announced. Its session, if any, is shared both ways."""
    from . import chats
    if not r.role:
        return
    c = next((c for c in chats.all_chats().values() if c.reminder == r.id), None)
    if c is None:
        name = r.id
        if chats._matching_name(name, [*chats.all_chats(), *chats.exposed_agents()]):
            name = chats._fresh_name(name)
        c = chats.Chat(name=name)
    c.role, c.reminder, c.about = r.role, r.id, r.title
    c.exposed = True
    if r.session and not c.session:
        c.session = r.session
    chats.upsert(c)


def announcement(r: Reminder, hits: list[str], why: str) -> str:
    lines = [f"[{r.id}] {r.title}"]
    if why == "due":
        lines.append(f"Due {when.fmt(r.due_dt)}" + (" (overdue)" if r.due_dt < _now() else ""))
    if hits:
        lines.append("New:")
        lines += [f"- {h}" for h in hits[:5]]
    if r.body.strip():
        first = next((l for l in r.body.splitlines() if l.strip()), "")
        lines.append(first[:200])
    if r.role:
        from . import chats
        name = next((c.name for c in chats.all_chats().values() if c.reminder == r.id), r.id)
        lines.append(f"Say 'talk {name}' to work on it, 'snooze {r.id} 2h' to push it.")
    else:
        lines.append(f"'snooze {r.id} 2h' pushes it; close it with `inbox remind done {r.id}`.")
    return "\n".join(lines)


# ---- the person's replies ------------------------------------------------------

_LAST_REPLY = paths.STATE / "last-reply.json"


def _last_reply_seen() -> str | None:
    if _LAST_REPLY.is_file():
        return json.loads(_LAST_REPLY.read_text()).get("id")
    return None


def _mark_reply_seen(mid: str) -> None:
    paths.STATE.mkdir(parents=True, exist_ok=True)
    _LAST_REPLY.write_text(json.dumps({"id": mid, "at": _stamp()}) + "\n")


def new_replies() -> list[dict]:
    """The person's messages on the reminder channel since the last pass."""
    via = config.reminders_via()
    try:
        rows = connectors.records(via, "search", "-n", "20", "--since", "2d")
    except SystemExit:
        return []
    rows = [m for m in rows if m.get("from") != "me"]
    rows.sort(key=lambda m: m.get("when", ""))
    last = _last_reply_seen()
    if last:
        ids = [m.get("id") for m in rows]
        if last in ids:
            rows = rows[ids.index(last) + 1:]
    else:                                         # first pass ever: nothing older than the loop counts
        rows = []
    return rows


def handle_reply(m: dict, dry_run: bool = False) -> str:
    """A message from the phone: the chat protocol decides. `snooze ID SPAN` is
    the one reminder command kept here, since a chat has no due time."""
    from . import chats
    text = (m.get("text") or "").strip()
    sn = re.match(r"^\s*snooze\s+(\S+)\s*(.*)$", text, re.I)
    if sn and any(r.id == sn.group(1) for r in open_reminders()):
        r = get(sn.group(1)); spec = sn.group(2).strip() or "2h"
        try:
            until = when.parse("in " + spec) if spec[0].isdigit() else when.parse(spec)
        except when.WhenError:
            until = _now() + timedelta(hours=2)
        r.status, r.due, r.told_at = "snoozed", _stamp(until), None
        r.note(f"snoozed until {_stamp(until)}"); r.save()
        tell(f"[{r.id}] snoozed until {when.fmt(until)}.", r, dry_run)
        return f"{r.id}: snoozed"
    return chats.handle(text, lambda t: tell(t, None, dry_run), dry_run)


def _ws_close(r: Reminder) -> None:
    for ref in r.refs:
        if ref.startswith("ws:task:") and shutil.which("ws"):
            subprocess.run(["ws", "edit", ref[3:], "--status", "done"], capture_output=True)
            log.record("task-done", channel="ws", ok=True, detail=ref[3:], reminder=r.id)


# ---- the agent session (via the reminder's chat) ----------------------------------

def converse(r: Reminder, prompt: str, dry_run: bool = False) -> str:
    """One turn with the reminder's role, from the terminal: the same chat the phone uses."""
    from . import chats
    ensure_chat(r)
    c = next((c for c in chats.all_chats().values() if c.reminder == r.id), None)
    if not c:
        return f"{r.id}: no role, so no chat; add one with --role"
    chats.set_current(c.name)
    ok, answer = chats.turn(c, prompt, dry_run)
    if dry_run:
        return answer
    if ok and c.session and c.session != r.session:
        r.session = c.session
    r.checked_at = _stamp(); r.note(f"turn: {prompt[:60]!r} -> {answer[:60]!r}"); r.save()
    tell(f"[{r.id}] {answer}" if ok else f"[{r.id}] could not run: {answer}", r)
    return f"{r.id}: turn {'ok' if ok else 'FAILED'}"


# ---- ws feed (due tasks without a reminder file) -----------------------------------

def ws_due_tasks(within: timedelta | None = None) -> list[Reminder]:
    if not shutil.which("ws"):
        return []
    try:
        listed = json.loads(subprocess.run(["ws", "list", "tasks", "--json"], capture_output=True, text=True, check=True).stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return []
    have = {ref for r in all_reminders() for ref in r.refs}
    horizon = _now() + (within or timedelta(0))
    out = []
    for item in listed:
        if item.get("status") in ("done", "closed", "cancelled") or f"ws:{item['ref']}" in have:
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
            out.append(Reminder(id="ws-" + item["ref"].split(":", 1)[1][:36], title=rec.get("name", item["ref"]),
                                due=_stamp(due_dt), refs=[f"ws:{item['ref']}"], body=str(rec.get("description", "")), status="pending"))
    return out


# ---- the pass ------------------------------------------------------------------

def run(dry_run: bool = False) -> list[str]:
    report: list[str] = []
    # 1. the person's replies
    replies = new_replies()
    for m in replies:
        report.append(handle_reply(m, dry_run))
    if replies and not dry_run:
        _mark_reply_seen(replies[-1]["id"])
    # 2. due tasks in ws without a reminder of their own become one
    for t in ws_due_tasks():
        if not dry_run:
            r = add(t.title, t.due_dt, t.refs, body=t.body, rid=t.id)
            report.append(f"{r.id}: reminder created from ws task")
    # 3. each open reminder: due, or watches hit?
    now = _now()
    for r in open_reminders():
        due = r.due_dt <= now and r.status != "told"
        hits = check_watches(r) if r.watches else []
        if not due and not hits:
            if r.watches and not dry_run:
                r.checked_at = _stamp(); r.save()
            continue
        why = "due" if due else "watch"
        if not dry_run:
            ensure_chat(r)
        ok, msg = tell(announcement(r, hits, why), r, dry_run)
        if ok and not dry_run:
            r.status, r.told_at, r.checked_at = "told", _stamp(), _stamp()
            r.note(f"told ({why})" + (f": {len(hits)} new" if hits else ""))
            r.save()
        report.append(f"{'told' if ok else 'FAILED'} {r.id} ({why})" + ("" if ok else f": {msg}") + (f"\n{msg}" if dry_run else ""))
    return report


def mark_done(rid: str) -> str:
    r = get(rid)
    r.status = "done"; r.note("done"); r.save()
    _ws_close(r)
    return f"{rid} done"


def snooze(rid: str, until: datetime) -> str:
    r = get(rid)
    r.status, r.due, r.told_at = "snoozed", _stamp(until), None
    r.note(f"snoozed until {_stamp(until)}"); r.save()
    return f"{rid} snoozed until {when.fmt(until)}"


# ---- launchd timer -------------------------------------------------------------

LAUNCHD_LABEL = "inbox.remind"
PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{label}</string>
  <key>ProgramArguments</key><array><string>{bin}</string><string>remind</string><string>run</string></array>
  <key>StartInterval</key><integer>{seconds}</integer>
  <key>RunAtLoad</key><true/>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>{path}</string></dict>
  <key>StandardOutPath</key><string>{log}</string>
  <key>StandardErrorPath</key><string>{log}</string>
</dict></plist>
"""


def _plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


def install_timer(every_minutes: int) -> str:
    import os
    plist = _plist_path()
    plist.parent.mkdir(parents=True, exist_ok=True)
    paths.LOG.mkdir(parents=True, exist_ok=True)
    binary = shutil.which("inbox")
    if not binary:
        raise SystemExit("inbox is not on PATH")
    try:
        login_path = subprocess.run(["zsh", "-lc", 'printf %s "$PATH"'], capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        login_path = ""
    plist.write_text(PLIST.format(label=LAUNCHD_LABEL, bin=binary, seconds=every_minutes * 60,
                                  path=login_path or os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
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
