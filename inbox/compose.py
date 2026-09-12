"""Compose a reminder message with an agent instead of the template.

The loop decides THAT a reminder is due; the agent decides what to say. It is
run headless with tools disabled, given the reminder and its dereferenced
refs, and its stdout becomes the message. It cannot send, read config, or
touch anything: the loop keeps policy, send and log. Any failure falls back
to the template, so a reminder is never lost.
"""
import json
import shutil
import subprocess

from . import config, paths

PROMPT_FILE = paths.HOME / "compose.md"

DEFAULT_PROMPT = """You write short reminder messages that are sent to {name} on their phone.

Write one message, a few sentences at most, in a natural direct tone, no preamble
and no signature. Say what is due, when it was due, and what {name} needs to do,
using the context below where it helps. If it is overdue, say so plainly. End
with one line telling them they can reply "done {id}" or "snooze {id} 2h".
Print only the message.

Reminder: {text}
Due: {due}
Status: {status}
Context:
{context}
"""


def _context(refs: list[str]) -> str:
    """Dereference what the tools on this machine can: a ws task record, a
    mail's header line. Anything else is passed through as text."""
    lines = []
    for ref in refs:
        kind, _, rest = ref.partition(":")
        if kind == "ws" and shutil.which("ws"):
            r = subprocess.run(["ws", "show", rest, "--json"], capture_output=True, text=True)
            if r.returncode == 0:
                try:
                    rec = json.loads(r.stdout)
                    keep = {k: rec[k] for k in ("name", "description", "status", "due", "priority") if k in rec}
                    lines.append(f"- {ref}: {json.dumps(keep, ensure_ascii=False)}")
                    continue
                except json.JSONDecodeError:
                    pass
            lines.append(f"- {ref}")
        elif kind == "email":
            channel, _, mid = rest.partition(":")
            try:
                from . import connectors
                rows = connectors.records(config.channel(channel), "read", mid)
                if rows:
                    m = rows[0]
                    lines.append(f"- {ref}: from {m.get('from_name') or m.get('from')}, subject '{m.get('subject')}', {m.get('when', '')[:10]}: {m.get('text', '')[:300]}")
                    continue
            except SystemExit:
                pass
            lines.append(f"- {ref}")
        else:
            lines.append(f"- {ref}")
    return "\n".join(lines) or "(none)"


def prompt_template() -> str:
    if PROMPT_FILE.is_file():
        return PROMPT_FILE.read_text(encoding="utf-8")
    return DEFAULT_PROMPT


def compose(r) -> str | None:
    """The agent's message for reminder r, or None when it cannot be had."""
    if not shutil.which("claude"):
        return None
    from . import when
    prompt = prompt_template().format(name=config.me().get("name", "the person"), text=r.text,
                                      due=when.fmt(r.due_dt), status=r.status, id=r.id, context=_context(r.refs))
    try:
        proc = subprocess.run(["claude", "-p", prompt, "--output-format", "text", "--tools", ""],
                              capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = proc.stdout.strip()
    if proc.returncode != 0 or not text or len(text) > 2000:
        return None
    return text


def enabled() -> bool:
    return bool(config.load().get("reminders", {}).get("compose", False))
