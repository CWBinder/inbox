"""Talking to connectors: the client commands on PATH that speak CONNECTORS.md.

inbox never imports a connector. It builds a command line from the channel's
connector and account, runs it, and parses the JSON that comes back. The
account flag and its position come from the connector's own `capabilities`.
"""
import json
import os
import shutil
import subprocess
from functools import lru_cache

from . import config


class ConnectorError(SystemExit):
    pass


def command(connector: str) -> str:
    cmd = config.connector_command(connector)
    if not shutil.which(cmd):
        raise ConnectorError(f"connector '{connector}': command '{cmd}' is not on PATH")
    return cmd


@lru_cache(maxsize=None)
def capabilities(connector: str) -> dict:
    r = subprocess.run([command(connector), "capabilities"], capture_output=True, text=True)
    if r.returncode != 0:
        raise ConnectorError(f"connector '{connector}': `capabilities` failed: {r.stderr.strip() or r.stdout.strip()}")
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        raise ConnectorError(f"connector '{connector}': `capabilities` did not return JSON")


def supports(connector: str, verb: str) -> bool:
    caps = capabilities(connector)
    return verb in caps.get("verbs", []) or verb in caps.get("optional", [])


def argv(channel: config.Channel, verb: str, *args: str, json_out: bool = True) -> list[str]:
    """The full command line for one verb on one channel."""
    caps = capabilities(channel.connector)
    flag = caps.get("account_flag", "--account")
    before = caps.get("account_position") == "before"
    cmd = [command(channel.connector)]
    if verb in ("accounts", "capabilities"):          # connector-wide verbs take no account
        cmd += [verb, *args]
    elif before:
        cmd += [flag, channel.account, verb, *args]
    else:
        cmd += [verb, *args, flag, channel.account]
    if json_out:
        cmd.append("--json")
    return cmd


def run(channel: config.Channel, verb: str, *args: str, env: dict | None = None):
    """Run a verb with --json and return (ok, parsed, raw_stderr, returncode)."""
    cmd = argv(channel, verb, *args)
    r = subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, **(env or {})})
    parsed = None
    if r.stdout.strip():
        try:
            parsed = json.loads(r.stdout)
        except json.JSONDecodeError:
            parsed = None
    return r.returncode == 0, parsed, (r.stderr.strip() or r.stdout.strip()), r.returncode


def passthrough(channel: config.Channel, verb: str, *args: str, env: dict | None = None) -> int:
    """Run a verb for a human: no --json, output straight to the terminal."""
    cmd = argv(channel, verb, *args, json_out=False)
    return subprocess.run(cmd, env={**os.environ, **(env or {})}).returncode


def send_env(connector: str) -> dict:
    """Environment that lifts a client's own send guard for one call. Policy
    is inbox's gate; the client's switch stays as a safety net for direct use."""
    return {"WHATSAPP_ALLOW_SEND": "1"} if connector == "whatsapp" else {}


def records(channel: config.Channel, verb: str, *args: str) -> list[dict]:
    """Message records from search or read, each stamped with the channel name."""
    ok, rows, err, _ = run(channel, verb, *args)
    if not ok or not isinstance(rows, list):
        raise ConnectorError(f"{channel.name} ({channel.connector}): {err}")
    for r in rows:
        r["channel"] = channel.name
    return rows


def resolve(channel: config.Channel, who: str) -> dict | None:
    """One connector's view of a recipient: {address, name, candidates} or None."""
    ok, res, _, code = run(channel, "resolve", who)
    if ok and isinstance(res, dict) and res.get("ok"):
        return res
    return None


def check(connector: str) -> list[tuple[str, str]]:
    """Conformance: does this connector implement the mandatory verbs? Returns (item, status) rows."""
    rows = []
    try:
        caps = capabilities(connector)
    except ConnectorError as e:
        return [("capabilities", f"FAIL {e}")]
    rows.append(("capabilities", "ok"))
    for verb in ("accounts", "search", "read", "send", "resolve"):
        rows.append((verb, "ok" if verb in caps.get("verbs", []) else "MISSING"))
    chs = config.channels_of(connector)
    if chs:
        ok, accounts, err, _ = run(chs[0], "accounts")
        rows.append(("accounts --json", "ok" if ok and isinstance(accounts, list) else f"FAIL {err[:80]}"))
        names = {a.get("name") for a in (accounts or [])} if isinstance(accounts, list) else set()
        for ch in chs:
            rows.append((f"channel {ch.name} -> account {ch.account}", "ok" if ch.account in names else "unknown account"))
        ok, rows_json, err, _ = run(chs[0], "search", "-n", "1")
        if ok and isinstance(rows_json, list):
            missing = [k for k in ("id", "account", "when", "from", "to", "subject", "text", "thread", "attachments") if rows_json and k not in rows_json[0]]
            rows.append(("search record", "ok" if not missing else f"missing keys: {', '.join(missing)}"))
        else:
            rows.append(("search --json", f"FAIL {err[:80]}"))
    else:
        rows.append(("channels", "none declared"))
    return rows
