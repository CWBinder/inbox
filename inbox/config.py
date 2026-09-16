"""~/.inbox/config.toml: who you are, and your channels.

A CHANNEL is your name for one account of one connector. A CONNECTOR is a
client command on PATH that speaks the contract (CONNECTORS.md); an ACCOUNT
is that client's own name for one set of credentials.

    [me]
    name = "Jane Doe"

    [connectors.gmail]      alias = "email"        # `inbox email ...` reaches this connector
    [connectors.whatsapp]   alias = "wa"

    [channels.work]     connector = "gmail"     account = "work"     default = true
    [channels.personal] connector = "gmail"     account = "personal"
    [channels.me]       connector = "whatsapp"  account = "default"  default = true  address = "4412345678"
    [channels.claude]   connector = "whatsapp"  account = "claude"

    [reminders]
    via = "claude"          # the channel reminders go out from
    to = "me"               # and the channel whose address they go to
"""
import tomllib
from dataclasses import dataclass
from functools import lru_cache

from . import paths


class ConfigError(SystemExit):
    pass


@dataclass(frozen=True)
class Channel:
    name: str
    connector: str
    account: str
    default: bool = False
    address: str | None = None      # this channel's own address, when known (needed for "me")


@lru_cache(maxsize=1)
def load() -> dict:
    if not paths.CONFIG.is_file():
        raise ConfigError(f"no config at {paths.CONFIG}; run `inbox init` first")
    with paths.CONFIG.open("rb") as fh:
        return tomllib.load(fh)


def me() -> dict:
    return load().get("me", {})


# ---- connectors ----------------------------------------------------------------

def connectors() -> dict[str, dict]:
    """Connector names -> their options. A connector appears here if any
    channel uses it, even without a [connectors.X] block."""
    declared = dict(load().get("connectors", {}))
    for ch in channels().values():
        declared.setdefault(ch.connector, {})
    return declared


def connector_command(name: str) -> str:
    return str(connectors().get(name, {}).get("command", name))


def alias_to_connector(word: str) -> str | None:
    """'wa' -> 'whatsapp', 'email' -> 'gmail', or a connector's own name."""
    for name, spec in connectors().items():
        if word == name or word == spec.get("alias"):
            return name
    return None


# ---- channels ------------------------------------------------------------------

@lru_cache(maxsize=1)
def channels() -> dict[str, Channel]:
    out = {}
    for name, spec in load().get("channels", {}).items():
        out[name] = Channel(name=name, connector=str(spec["connector"]), account=str(spec.get("account", "default")),
                            default=bool(spec.get("default", False)), address=(str(spec["address"]) if "address" in spec else None))
    return out


def channel(name: str) -> Channel:
    chs = channels()
    if name not in chs:
        raise ConfigError(f"unknown channel '{name}'; known: {', '.join(chs) or 'none (inbox channel add ...)'}")
    return chs[name]


def channels_of(connector: str) -> list[Channel]:
    return [c for c in channels().values() if c.connector == connector]


def default_channel(connector: str) -> Channel:
    chs = channels_of(connector)
    if not chs:
        raise ConfigError(f"no channel uses connector '{connector}'")
    for c in chs:
        if c.default:
            return c
    if len({c.account for c in chs}) == 1:
        return chs[0]
    raise ConfigError(f"several channels use '{connector}' and none is default; pass --via one of: {', '.join(c.name for c in chs)}")


def resolve_via(via: str | None, connector: str | None = None) -> Channel:
    """The channel a command acts on: --via when given, else the connector's default."""
    if via:
        ch = channel(via)
        if connector and ch.connector != connector:
            raise ConfigError(f"channel '{via}' is on {ch.connector}, not {connector}")
        return ch
    if connector:
        return default_channel(connector)
    raise ConfigError("say where: --via CHANNEL (inbox channel list)")


# ---- reminders -----------------------------------------------------------------

def reminders_via() -> Channel:
    return channel(str(load().get("reminders", {}).get("via", "claude")))


def reminders_to() -> Channel:
    return channel(str(load().get("reminders", {}).get("to", "me")))
