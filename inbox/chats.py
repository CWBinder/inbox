"""Phone conversations and an explicit catalog of exposed agents.

`chats` shows agents (always start fresh) and conversations (resume).
Fresh conversations stay out of the catalog until `save NAME`; reminders
expose their own conversation when announced. One conversation is current.
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
AGENTS = paths.HOME / "agents.toml"
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
    backend: str = "claude"               # existing entries remain Claude sessions
    exposed: bool = True                  # old saved conversations remain available


def _load() -> dict[str, Chat]:
    if not CHATS.is_file():
        return {}
    with CHATS.open("rb") as fh:
        data = tomllib.load(fh)
    out = {}
    for name, spec in (data.get("chats") or {}).items():
        out[name] = Chat(name=name, session=spec.get("session") or None, role=spec.get("role") or None,
                         about=str(spec.get("about", "")), reminder=spec.get("reminder") or None,
                         cwd=spec.get("cwd") or None, backend=str(spec.get("backend", "claude")),
                         exposed=bool(spec.get("exposed", True)))
    return out


def _save(chats: dict[str, Chat]) -> None:
    lines = ["# Chats you can talk to from the phone: `talk NAME`. Managed by inbox; edit freely.", ""]
    for c in chats.values():
        lines.append(f"[chats.{json.dumps(c.name)}]")
        if not c.exposed:
            lines.append("exposed = false")
        if c.backend != "claude":
            lines.append(f"backend = {json.dumps(c.backend)}")
        for key in ("session", "role", "reminder", "cwd"):
            v = getattr(c, key)
            if v:
                lines.append(f"{key} = {json.dumps(v)}")
        if c.about:
            lines.append(f"about = {json.dumps(c.about)}")
        lines.append("")
    CHATS.parent.mkdir(parents=True, exist_ok=True)
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
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 -]{0,62}[A-Za-z0-9]|[A-Za-z0-9]", name))


def exposed_agents() -> dict[str, dict[str, str]]:
    if not AGENTS.is_file():
        return {}
    with AGENTS.open("rb") as fh:
        return tomllib.load(fh).get("agents", {})


def _save_agents(agents: dict[str, dict[str, str]]) -> None:
    lines = ["# Agents explicitly exposed to the phone. Each selection starts fresh.", ""]
    for name, spec in agents.items():
        lines += [f"[agents.{json.dumps(name)}]", f"role = {json.dumps(spec['role'])}",
                  f"about = {json.dumps(spec.get('about', ''))}", ""]
    AGENTS.parent.mkdir(parents=True, exist_ok=True)
    AGENTS.write_text("\n".join(lines), encoding="utf-8")


def _matching_name(name: str, names) -> str | None:
    return next((n for n in names if n.casefold() == name.casefold()), None)


def _agent_match(selector: str, agents: dict[str, dict[str, str]] | None = None) -> tuple[str, dict[str, str]] | None:
    """An exposed agent is addressable by its friendly name or roster role."""
    source = exposed_agents() if agents is None else agents
    for name, spec in source.items():
        if selector.casefold() in (name.casefold(), str(spec["role"]).casefold()):
            return name, spec
    return None


def _agent_selectors(agents: dict[str, dict[str, str]] | None = None) -> list[str]:
    out = []
    source = exposed_agents() if agents is None else agents
    for name, spec in source.items():
        out += [name, str(spec["role"])]
    return out


def check_conversation_name(name: str) -> None:
    if not valid_name(name):
        raise ValueError("Use a short name with letters, digits, spaces or dashes (up to 64 characters).")
    matched = _agent_match(name)
    if matched:
        agent_name, spec = matched
        raise ValueError(f"'{name}' selects the exposed agent '{agent_name}' ({spec['role']}). Choose a different conversation name.")
    other = _matching_name(name, _load())
    if other and other != name:
        raise ValueError(f"A conversation named '{other}' already exists. Use that spelling or another name.")


def expose_agent(role: str, name: str | None = None, about: str | None = None) -> str:
    catalog = roles.available()
    actual_role = _matching_name(role, catalog)
    if not actual_role:
        raise ValueError(f"No roster role '{role}'. Use 'roster list roles' to see available roles.")
    agents = exposed_agents()
    same_role = next(((n, spec) for n, spec in agents.items()
                      if str(spec["role"]).casefold() == actual_role.casefold()), None)
    name = name or (same_role[0] if same_role else actual_role)
    if not valid_name(name):
        raise ValueError("Use a short agent name with letters, digits, spaces or dashes.")
    chats = _load()
    conflict = _matching_name(name, chats) or _matching_name(actual_role, chats)
    if conflict:
        raise ValueError(f"'{conflict}' already names a conversation. Choose a different agent name or conversation name.")
    others = {n: spec for n, spec in agents.items() if not same_role or n != same_role[0]}
    conflict = _agent_match(name, others) or _agent_match(actual_role, others)
    if conflict:
        existing, _ = conflict
        raise ValueError(f"An agent named '{existing}' is already exposed. Choose a different name.")
    if same_role and same_role[0] != name:
        del agents[same_role[0]]
    previous = same_role[1] if same_role else agents.get(name, {})
    agents[name] = {"role": actual_role,
                    "about": about if about is not None else previous.get("about", catalog[actual_role])}
    _save_agents(agents)
    return name


def hide_agent(name: str) -> bool:
    agents = exposed_agents()
    matched = _agent_match(name, agents)
    if not matched:
        return False
    actual, _ = matched
    del agents[actual]
    _save_agents(agents)
    return True


def hide_conversation(name: str) -> bool:
    actual = _matching_name(name, _load())
    chat = get(actual) if actual else None
    if not chat:
        return False
    chat.exposed = False
    upsert(chat)
    return True


def _fresh_name(base: str) -> str:
    names = [*_load(), *_agent_selectors()]
    n = 1
    while True:
        suffix = f" {n}"
        name = base[:64 - len(suffix)].rstrip() + suffix
        if not _matching_name(name, names):
            return name
        n += 1


def select(name: str) -> Chat:
    """An exposed agent always starts fresh; an exposed conversation resumes."""
    agents = exposed_agents()
    matched = _agent_match(name, agents)
    if matched:
        agent_name, spec = matched
        if not roles.system_prompt(spec['role']):
            raise ValueError(f"Could not load instructions for agent '{agent_name}'. Check its roster role on the Mac.")
        chat = upsert(Chat(name=_fresh_name(agent_name), role=spec['role'], exposed=False))
    else:
        actual = _matching_name(name, [c.name for c in _load().values() if c.exposed])
        chat = get(actual) if actual else None
        if chat is None:
            raise ValueError(f"No exposed agent or conversation '{name}'. Say 'chats' to see what is available.")
    set_current(chat.name)
    return chat


def save_current(name: str) -> Chat:
    """Give the current conversation a name without duplicating its session."""
    check_conversation_name(name)
    chats = _load()
    old = current()
    if old not in chats:
        raise ValueError("No current chat. Say 'talk ROLE' or 'talk NAME' first.")
    if name != old and name in chats:
        raise ValueError(f"A chat named '{name}' already exists. Choose another name.")
    chat = chats.pop(old)
    chat.name = name
    chat.exposed = True
    chats[name] = chat
    _save(chats)
    set_current(name)
    return chat


# ---- listing for the phone -------------------------------------------------------

def role_listing() -> str:
    lines = ["Agents — start a new conversation"]
    for name, spec in sorted(exposed_agents().items(), key=lambda item: item[0].casefold()):
        role = str(spec["role"])
        alias = f" ({role})" if role.casefold() != name.casefold() else ""
        lines.append(f"• {name}{alias}" + _description(spec.get('about', '')))
    if len(lines) == 1:
        lines.append("None exposed yet.")
    return "\n".join(lines)


def _description(text: str) -> str:
    summary = " ".join(text.split())
    if len(summary) > 90:
        summary = summary[:87].rsplit(" ", 1)[0] + "…"
    return f" — {summary}" if summary else ""


def listing() -> str:
    chats = sorted((c for c in _load().values() if c.exposed), key=lambda c: c.name.casefold())
    cur = current()
    lines = [role_listing(), "", "Conversations — resume where you left off"]
    for c in chats:
        mark = " (current)" if c.name == cur else ""
        ready = " (not started)" if not c.session else ""
        lines.append(f"• {c.name}{mark}{ready}" + _description(c.about))
    if not chats:
        lines.append("None exposed yet.")
    lines += ["", "talk NAME → select, then send your message.", "save NAME → keep the current conversation in this list."]
    active = get(cur) if cur else None
    if active and not active.exposed:
        lines.append(f"Current: {cur} (not saved to this list).")
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
    if chat.backend == "codex":
        from . import codex
        ok, answer = codex.turn(chat.session, prompt, cwd=chat.cwd, dry_run=dry_run)
        if not dry_run:
            log.record("chat-turn", channel=config.reminders_via().name, ok=ok, detail=prompt[:200],
                       result=answer[:200], chat=chat.name, session=chat.session, backend="codex")
        return ok, answer
    if chat.backend != "claude":
        return False, f"unknown chat backend '{chat.backend}'"
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

_CMD = re.compile(r"^\s*(?:(roles|agents|chats|available|available chats|done|who)|(talk|save|new)(?:[ \t]+([^\r\n]+?))?)\s*$", re.I)


def handle(text: str, tell, dry_run: bool = False) -> str:
    """One message from the phone. `tell(text)` sends a reply. Returns a report line."""
    text = text.strip()
    m = _CMD.match(text)
    if m:
        cmd, arg = (m.group(1) or m.group(2)).lower(), m.group(3)
        if cmd in ("roles", "agents", "chats", "available", "available chats", "who"):
            tell(listing()); return "listed chats"
        if cmd == "talk":
            if not arg:
                tell(listing())
                return "listed talk choices"
            try:
                c = select(arg)
            except ValueError as e:
                tell(str(e)); return f"talk: unavailable {arg}"
            action = "New conversation" if not c.session else "Resuming conversation"
            tell(f"[{c.name}] {action}. Send your message." + (" Use 'save NAME' to keep it in chats." if not c.exposed else ""))
            return f"talk {arg}"
        if cmd == "save":
            try:
                c = save_current(arg or "")
            except ValueError as e:
                tell(str(e)); return "save: unavailable"
            tell(f"[{c.name}] saved. Return to this conversation with 'talk {c.name}'.")
            return f"saved {c.name}"
        if cmd == "new":
            try:
                check_conversation_name(arg or "")
            except ValueError as e:
                tell(str(e)); return "new: bad name"
            if get(arg):
                tell(f"[{arg}] exists; say 'talk {arg}'."); return f"new: exists {arg}"
            upsert(Chat(name=arg, exposed=False)); set_current(arg)
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
