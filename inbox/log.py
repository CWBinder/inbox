"""Audit trail: one JSON line per side effect taken on the person's behalf."""
import json
import os
from datetime import datetime, timedelta, timezone

from . import paths


def record(action: str, *, channel: str, ok: bool, recipient: str | None = None,
           detail: str = "", **extra) -> None:
    paths.LOG.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "action": action, "channel": channel, "recipient": recipient, "ok": ok,
        "detail": detail[:500], "by": os.environ.get("INBOX_ACTOR") or os.environ.get("USER"),
        **extra,
    }
    with paths.LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def parse_since(text: str) -> datetime:
    """'7d', '24h', '30m' or an ISO date."""
    units = {"d": "days", "h": "hours", "m": "minutes"}
    if text and text[-1] in units and text[:-1].isdigit():
        return datetime.now().astimezone() - timedelta(**{units[text[-1]]: int(text[:-1])})
    return datetime.fromisoformat(text).astimezone()


def entries(since: datetime | None = None) -> list[dict]:
    if not paths.LOG_FILE.is_file():
        return []
    out = []
    for line in paths.LOG_FILE.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if since and datetime.fromisoformat(e["ts"]) < since:
            continue
        out.append(e)
    return out
