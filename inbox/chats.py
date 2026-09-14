"""Chats: named conversations you can talk to from your phone.

~/.inbox/chats.toml lists them. Each has a name, optionally a claude session
to resume and a roster role to start fresh from, and a one-line `about`.
One chat is current; a message from the phone is either a command (chats,
talk NAME, new NAME, done) or a prompt for the current chat. Every bot
message starts with [name]. No routing, no guessing: with no current chat
the bot says so and lists the names.

A reminder with a role becomes a chat of the same name when it is announced.
"""
import json
import re
import shutil
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

from . import config, connectors, log, paths, roles

CHATS = paths.HOME / "chats.toml"
CURRENT = paths.STATE / "current-chat.json"
TOOLS = "Read Glob Grep Bash(inbox:*) Bash(ws:*) Bash(pplx:*) Bash(gmail:*) Bash(whatsapp:*) Bash(telegram:*) Bash(roster:*)"


@dataclass
class Chat:
    name: str
    session: str | None = None
    role: str | None = None
    about: str = ""
    reminder: str | None = None            # a reminder id this chat is about, if any
    cwd: str | None = None                 # working folder for fresh sessions


def _load() -> dict[str, Chat]:
    if not CHATS.is_file():
        return {}
    with CHATS.open("rb") as fh:
        data = tomllib.load(fh)
    out = {}
    for name, spec in (data.get("chats") or {}).items():
        out[name] = Chat(name=name, session=spec.get("session") or None, role=spec.get("role") or None,
                         about=str(spec.get("about", "")), reminder=spec.get("reminder") or None, cwd=spec.get("cwd") or None)
    return out


def _save(chats: dict[str, Chat]) -> None:
    lines = ["# Chats you can talk to from the phone: `talk NAME`. Managed by inbox; edit freely.", ""]
    for c in chats.values():
        lines.append(f"[chats.{c.name}]")
        for key in ("session", "role", "reminder", "cwd"):
            v = getattr(c, key)
            if v:
                lines.append(f"{key} = {json.dumps(v)}")
        if c.about:
            lines.append(f"about = {json.dumps(c.about)}")
        lines.append("")
    CHATS.write_text("\n".join(lines), encoding="utf-8")


def all_chats() -> dict[str, Chat]:
    return _load()


def get(name: str) -> Chat | None:
    return _load().get(name)


def upsert(chat: Chat) -> Chat:
    chats = _load()
    chats[chat.name] = chat
    _save(chats)
    return chat


def remove(name: str) -> bool:
    chats = _load()
    if name not in chats:
        return False
    del chats[name]
    _save(chats)
    if current() == name:
        set_current(None)
    return True


def current() -> str | None:
    if CURRENT.is_file():
        return json.loads(CURRENT.read_text()).get("name")
    return None


def set_current(name: str | None) -> None:
    paths.STATE.mkdir(parents=True, exist_ok=True)
    CURRENT.write_text(json.dumps({"name": name}) + "\n")


def valid_name(name: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,30}", name))


# ---- listing for the phone -------------------------------------------------------

def listing() -> str:
    chats = _load()
    if not chats:
        return "No chats yet. Say 'new NAME' to start one."
    cur = current()
    lines = ["Chats (say 'talk NAME'):"]
    for c in chats.values():
        mark = "*" if c.name == cur else " "
        state = "session" if c.session else (f"fresh, role {c.role}" if c.role else "fresh")
        lines.append(f"{mark} {c.name}  {c.about or ''}  [{state}]")
    return "\n".join(lines)


# ---- one turn --------------------------------------------------------------------

def _system_prompt(chat: Chat) -> str:
    base = roles.system_prompt(chat.role) if chat.role else ""
    person = config.me().get("name", "the person")
    extra = ""
    if chat.reminder:
        from . import reminders
        try:
            r = reminders.get(chat.reminder)
            extra = f"\n\n--- reminder {r.id} ---\n{r.render_file()}"
        except SystemExit:
            pass
    return (base + "\n\n" if base else "") + f"""You are talking to {person} through a bot on their phone, in a chat named "{chat.name}"{(' about ' + chat.about) if chat.about else ''}.
Each message you receive is their instruction; your final answer is sent back verbatim. Answer in a few short
sentences, outcome first, no preamble, no markdown headings. If you need a yes before acting, ask in one sentence
and stop. Sending a message or mail needs their explicit yes in this conversation; pass --confirmed only then.{extra}"""


def turn(chat: Chat, prompt: str, dry_run: bool = False) -> tuple[bool, str]:
    """Run one turn: resume the chat's session, or start fresh. Returns (ok, answer)."""
    if not shutil.which("claude"):
        return False, "claude is not on PATH"
    argv = ["claude", "-p", prompt, "--output-format", "json", "--allowedTools", TOOLS]
    if chat.session:
        argv += ["--resume", chat.session]
    else:
        argv += ["--system-prompt", _system_prompt(chat)]
    if dry_run:
        return True, f"would {'resume ' + chat.session if chat.session else 'start fresh'} in [{chat.name}] with: {prompt[:80]}"
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=900, cwd=chat.cwd or None)
        data = json.loads(proc.stdout) if proc.stdout.strip() else {}
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        return False, f"could not run: {e}"
    answer = str(data.get("result") or "").strip()
    if data.get("is_error") or not answer:
        reason = answer[:200] or proc.stderr[:200]
        if "authenticate" in reason.lower() or "oauth" in reason.lower():
            reason += " (run `claude login` on the Mac)"
        log.record("chat-turn", channel=config.reminders_via().name, ok=False, detail=prompt[:200], result=reason, chat=chat.name)
        return False, reason
    sid = data.get("session_id")
    if sid and sid != chat.session:
        chat.session = sid
        upsert(chat)
    log.record("chat-turn", channel=config.reminders_via().name, ok=True, detail=prompt[:200], result=answer[:200],
               chat=chat.name, session=sid, cost=data.get("total_cost_usd"))
    return True, answer


# ---- the phone protocol -----------------------------------------------------------

_CMD = re.compile(r"^\s*(chats|talk|new|done|who)\b\s*(\S+)?\s*$", re.I)


def handle(text: str, tell, dry_run: bool = False) -> str:
    """One message from the phone. `tell(text)` sends a reply. Returns a report line."""
    text = text.strip()
    m = _CMD.match(text)
    if m:
        cmd, arg = m.group(1).lower(), m.group(2)
        if cmd in ("chats", "who"):
            tell(listing()); return "listed chats"
        if cmd == "talk":
            if not arg or not get(arg):
                tell(f"No chat '{arg or ''}'.\n" + listing()); return f"talk: unknown {arg}"
            set_current(arg)
            c = get(arg)
            tell(f"[{arg}] talking to {arg}" + (f": {c.about}" if c.about else "") + ". What should I do?")
            return f"talk {arg}"
        if cmd == "new":
            if not arg or not valid_name(arg):
                tell("Say 'new NAME' with a short lowercase name."); return "new: bad name"
            if get(arg):
                tell(f"[{arg}] exists; say 'talk {arg}'."); return f"new: exists {arg}"
            upsert(Chat(name=arg)); set_current(arg)
            tell(f"[{arg}] new chat. What should I do?"); return f"new {arg}"
        if cmd == "done":
            cur = current()
            if not cur:
                tell("No current chat."); return "done: none"
            c = get(cur)
            closed = ""
            if c and c.reminder:
                from . import reminders
                try:
                    reminders.mark_done(c.reminder); closed = f"; reminder {c.reminder} closed"
                except SystemExit:
                    pass
            remove(cur)
            tell(f"[{cur}] done{closed}. " + listing()); return f"done {cur}"
    cur = current()
    if not cur or not get(cur):
        tell("No current chat. " + listing()); return "prompt without a chat"
    c = get(cur)
    tell(f"[{c.name}] on it.")
    ok, answer = turn(c, text, dry_run)
    if dry_run:
        return answer
    tell(f"[{c.name}] {answer}" if ok else f"[{c.name}] could not run: {answer}")
    return f"[{c.name}] turn {'ok' if ok else 'FAILED'}"
