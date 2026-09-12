"""~/.inbox/policy.toml: what may be sent, from which channel, to whom.

    [defaults]
    send = "confirm"           # deny | draft-only | confirm | allow
    destructive = "deny"       # trash, draft-delete

    [channels.work]
    send = "draft-only"        # agents draft, the person sends

    [channels.claude]
    send = "allow"             # the assistant's number may message ...
    allow_to = ["me"]          # ... only these recipients (channel names or raw addresses)

Levels: deny/draft-only refuse; confirm requires --confirmed, asserting the
person approved this exact recipient and text; allow needs nothing. Missing
keys fall back to [defaults], then to the most restrictive level.
"""
import tomllib
from dataclasses import dataclass
from functools import lru_cache

from . import config, paths

LEVELS = ("deny", "draft-only", "confirm", "allow")


@lru_cache(maxsize=1)
def load() -> dict:
    if not paths.POLICY.is_file():
        return {}
    with paths.POLICY.open("rb") as fh:
        return tomllib.load(fh)


@dataclass
class Verdict:
    allowed: bool
    reason: str


def _level(*lookups, default: str) -> str:
    for v in lookups:
        if v in LEVELS:
            return v
    return default


def _decide(level: str, confirmed: bool, what: str) -> Verdict:
    if level in ("deny", "draft-only"):
        return Verdict(False, f"policy: {what} is '{level}'")
    if level == "confirm" and not confirmed:
        return Verdict(False, f"policy: {what} needs --confirmed (the person approved this exact message)")
    return Verdict(True, f"policy: {what} '{level}'")


def _channel_rules(name: str) -> dict:
    return load().get("channels", {}).get(name, {})


def send(channel: config.Channel, recipient: str, confirmed: bool) -> Verdict:
    rules, defaults = _channel_rules(channel.name), load().get("defaults", {})
    level = _level(rules.get("send"), defaults.get("send"), default="confirm")
    allow_to = rules.get("allow_to")
    if allow_to is not None:
        from . import connectors                                 # late import: connectors imports config, not policy
        targets = set()
        for t in allow_to:
            targets.add(str(t))
            ch = config.channels().get(str(t))
            if ch and ch.address and ch.connector == channel.connector:
                targets.add(ch.address)
            res = connectors.resolve(channel, str(t))            # what this name means on the sending service
            if res:
                targets.add(res["address"])
        if recipient not in targets:
            return Verdict(False, f"policy: channel '{channel.name}' may only message {sorted(allow_to)}")
    return _decide(level, confirmed, f"send via '{channel.name}'")


def draft(channel: config.Channel) -> Verdict:
    """Drafting is allowed unless the channel is fully denied."""
    rules, defaults = _channel_rules(channel.name), load().get("defaults", {})
    level = _level(rules.get("send"), defaults.get("send"), default="confirm")
    if level == "deny":
        return Verdict(False, f"policy: channel '{channel.name}' is 'deny'")
    return Verdict(True, f"policy: draft via '{channel.name}'")


def destructive(channel: config.Channel, confirmed: bool, what: str) -> Verdict:
    rules, defaults = _channel_rules(channel.name), load().get("defaults", {})
    level = _level(rules.get("destructive"), defaults.get("destructive"), default="deny")
    return _decide(level, confirmed, f"{what} via '{channel.name}'")
