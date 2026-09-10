"""~/.pa/config.toml: accounts, identities, who the person is.

    [me]
    name = "Jane Doe"
    whatsapp = "4412345678"          # own number, for reminders and "me" recipients

    [email]
    default = "work"
    [email.accounts.work]     address = "jane@work.example"
    [email.accounts.personal] address = "jane@example.com"

    [whatsapp]
    default = "me"
    [whatsapp.identities.me]     profile = "default"   # profile name in the whatsapp client
    [whatsapp.identities.claude] profile = "claude"    # the assistant's own number
"""
import tomllib
from functools import lru_cache

from . import paths


class ConfigError(SystemExit):
    pass


@lru_cache(maxsize=1)
def load() -> dict:
    if not paths.CONFIG.is_file():
        raise ConfigError(f"no config at {paths.CONFIG}; run `pa init` first")
    with paths.CONFIG.open("rb") as fh:
        return tomllib.load(fh)


def me() -> dict:
    return load().get("me", {})


# ---- email -------------------------------------------------------------------

def email_accounts() -> dict[str, dict]:
    return load().get("email", {}).get("accounts", {})


def email_default() -> str | None:
    return load().get("email", {}).get("default")


def email_account(name: str | None) -> str:
    accounts = email_accounts()
    chosen = name or email_default()
    if not chosen:
        raise ConfigError("no email account given and no [email] default in config")
    if accounts and chosen not in accounts:
        raise ConfigError(f"unknown email account '{chosen}'; known: {', '.join(accounts)}")
    return chosen


# ---- whatsapp ----------------------------------------------------------------

def whatsapp_identities() -> dict[str, dict]:
    return load().get("whatsapp", {}).get("identities", {})


def whatsapp_default() -> str:
    return load().get("whatsapp", {}).get("default", "me")


def whatsapp_identity(name: str | None) -> tuple[str, str]:
    """Return (identity name, whatsapp client profile)."""
    idents = whatsapp_identities()
    chosen = name or whatsapp_default()
    if chosen not in idents:
        known = ", ".join(idents) or "none declared"
        raise ConfigError(f"unknown WhatsApp identity '{chosen}'; known: {known}")
    return chosen, str(idents[chosen].get("profile", "default"))
