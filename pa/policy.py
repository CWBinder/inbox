"""~/.pa/policy.toml: what may be sent, by whom, to whom, with what confirmation.

    [email]
    send = "draft-only"        # draft-only | confirm | allow
    destructive = "deny"       # deny | confirm | allow   (trash, draft-delete)

    [whatsapp]
    send = "confirm"           # confirm: the caller must pass --confirmed,
                               # asserting the person approved this exact message

    [whatsapp.identities.claude]
    send = "allow"
    allow_to = ["me"]          # only these recipients; "me" is [me].whatsapp in config

Levels: "deny"/"draft-only" refuse; "confirm" requires --confirmed; "allow" needs nothing.
Missing keys default to the most restrictive level.
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


def _level(*lookups: str | None, default: str) -> str:
    for v in lookups:
        if v in LEVELS:
            return v
    return default


def _decide(level: str, confirmed: bool, what: str) -> Verdict:
    if level in ("deny", "draft-only"):
        return Verdict(False, f"policy: {what} is '{level}'")
    if level == "confirm" and not confirmed:
        return Verdict(False, f"policy: {what} needs --confirmed (the person approved this exact message)")
    return Verdict(True, f"policy: {what} '{level}'" + (" with confirmation" if confirmed and level == "confirm" else ""))


def email_send(confirmed: bool) -> Verdict:
    level = _level(load().get("email", {}).get("send"), default="draft-only")
    return _decide(level, confirmed, "email send")


def email_destructive(confirmed: bool, what: str) -> Verdict:
    level = _level(load().get("email", {}).get("destructive"), default="deny")
    return _decide(level, confirmed, f"email {what}")


def whatsapp_send(identity: str, recipient: str, confirmed: bool) -> Verdict:
    wa = load().get("whatsapp", {})
    ident = wa.get("identities", {}).get(identity, {})
    level = _level(ident.get("send"), wa.get("send"), default="confirm")
    allow_to = ident.get("allow_to")
    if allow_to is not None:
        me_number = str(config.me().get("whatsapp", ""))
        targets = {("me" if t == "me" else str(t)) for t in allow_to}
        ok = recipient in targets or (me_number and recipient == me_number and "me" in targets)
        if not ok:
            return Verdict(False, f"policy: identity '{identity}' may only message {sorted(targets)}")
    return _decide(level, confirmed, f"whatsapp send as '{identity}'")
