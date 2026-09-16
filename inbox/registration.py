"""Discover connector accounts and register canonical connector.account channels."""
import json
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
from pathlib import Path

from . import config, connectors, paths


class RegistrationError(SystemExit):
    pass


def _identifier(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_-]*", value):
        raise RegistrationError(f"{label} must start with a lowercase letter and contain only lowercase letters, digits, '-' or '_' (got {value!r})")
    return value


def _query(command, *args):
    try:
        result = subprocess.run([command, *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RegistrationError(f"connector discovery failed: {exc}") from exc
    if result.returncode and not (args == ('accounts', '--json') and result.returncode == 1):
        raise RegistrationError(f"connector {' '.join(args)} failed (exit {result.returncode}); check its setup directly")
    try:
        data = json.loads(result.stdout)
    except ValueError as exc:
        raise RegistrationError(f"connector {' '.join(args)} did not return valid JSON") from exc
    # Existing clients exit 1 when listing accounts whose authentication failed.
    # Accept only a structured account-status response in that case.
    if result.returncode and not (isinstance(data, list) and data
            and all(isinstance(a, dict) and isinstance(a.get('ok'), bool) for a in data)
            and any(not a['ok'] for a in data)):
        raise RegistrationError('accounts failed without a valid account-status response')
    return data


def _extend_table(text, group, name, fields):
    """Add missing fields without rewriting comments or unrelated configuration."""
    document = tomllib.loads(text)
    existing = document.get(group, {}).get(name)
    fields = {key: value for key, value in fields.items() if existing is None or key not in existing}
    if not fields:
        return text
    body = ''.join(f'{key} = {json.dumps(value)}\n' for key, value in fields.items())
    if existing is None:
        return text.rstrip() + f'\n\n[{group}.{json.dumps(name)}]\n' + body
    # Recognize quoted as well as bare table names using TOML's own parser.
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if not line.lstrip().startswith('['):
            continue
        try:
            header = tomllib.loads(line)
        except tomllib.TOMLDecodeError:
            continue
        if header == {group: {name: {}}}:
            lines[index] = line.rstrip('\n') + '\n' + body
            return ''.join(lines)
    raise RegistrationError(f"Use a dedicated [{group}.{json.dumps(name)}] table before registering this connector")


def register(executable, reserved=()):
    command = shutil.which(str(Path(executable).expanduser()))
    if not command:
        raise RegistrationError(f"executable '{executable}' not found; install it on PATH or pass its full path")
    command = os.path.abspath(command)
    caps = _query(command, 'capabilities')
    if not isinstance(caps, dict):
        raise RegistrationError('capabilities must return a JSON object')
    name = _identifier(caps.get('connector'), 'connector name')
    if name in reserved:
        raise RegistrationError(f"connector name '{name}' conflicts with an Inbox command or connector alias")
    verbs = caps.get('verbs')
    required = {'accounts', 'threads', 'search', 'read', 'send', 'resolve'}
    if not isinstance(verbs, list) or not all(isinstance(v, str) for v in verbs) or not required.issubset(verbs):
        raise RegistrationError('capabilities must advertise accounts, threads, search, read, send, and resolve')
    flag = caps.get('account_flag')
    if not isinstance(flag, str) or not re.fullmatch(r'--[a-zA-Z][a-zA-Z0-9-]*', flag):
        raise RegistrationError('capabilities must advertise an account_flag such as --account')
    if caps.get('account_position', 'after') not in ('before', 'after'):
        raise RegistrationError('account_position must be before or after')
    accounts = _query(command, 'accounts', '--json')
    if not isinstance(accounts, list) or not accounts:
        raise RegistrationError('accounts must return a nonempty JSON list; configure an account in the connector first')
    seen = set()
    for account in accounts:
        if not isinstance(account, dict):
            raise RegistrationError('each account must be a JSON object')
        ident = _identifier(account.get('name'), 'account name')
        if ident in seen:
            raise RegistrationError(f"duplicate account '{ident}'")
        seen.add(ident)
        if not isinstance(account.get('ok'), bool):
            raise RegistrationError(f"account '{ident}' must report a boolean ok status")
        if 'default' in account and not isinstance(account['default'], bool):
            raise RegistrationError(f"account '{ident}' must report a boolean default")
        if account.get('address') is not None and not isinstance(account['address'], str):
            raise RegistrationError(f"account '{ident}' must report a string or null address")
    if sum(a.get('default', False) for a in accounts) > 1:
        raise RegistrationError('connector reports more than one default account')

    if not paths.CONFIG.is_file():
        raise RegistrationError('run `inbox init` before registering a connector')
    original = paths.CONFIG.read_text(encoding='utf-8')
    document = tomllib.loads(original)
    old_spec = document.get('connectors', {}).get(name, {})
    channel_specs = document.get('channels', {})
    existing_command = old_spec.get('command', name)
    used = bool(old_spec) or any(c.get('connector') == name for c in channel_specs.values())
    if used and os.path.abspath(shutil.which(existing_command) or existing_command) != command:
        raise RegistrationError(f"connector '{name}' already uses another executable; update its command mapping explicitly first")
    text = _extend_table(original, 'connectors', name, {'command': command})
    has_default = any(c.get('connector') == name and c.get('default') for c in channel_specs.values())
    report = []
    for account in accounts:
        ident = account['name']
        canonical = f'{name}.{ident}'
        old = channel_specs.get(canonical)
        if old is not None:
            if old.get('connector') != name or old.get('account') != ident:
                raise RegistrationError(f"channel '{canonical}' already refers to another account")
        else:
            fields = {'connector': name, 'account': ident}
            aliases = [key for key, spec in channel_specs.items()
                       if spec.get('connector') == name and spec.get('account') == ident]
            if len(aliases) > 1:
                raise RegistrationError(f"multiple existing channels refer to {canonical}; consolidate them before registration")
            if aliases:
                # Preserve the old channel's sending restrictions under the new name.
                fields['policy_channel'] = aliases[0]
            if account.get('address'):
                fields['address'] = account['address']
            if not has_default and (account.get('default') or len(accounts) == 1):
                fields['default'] = True
                has_default = True
            text = _extend_table(text, 'channels', canonical, fields)
        state = 'ok' if account['ok'] else 'unavailable; check authentication or connector status'
        report.append(f"{canonical}: {state}")
    tomllib.loads(text)  # Validate the complete result before touching the user's file.
    if text != original:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=paths.CONFIG.parent, delete=False) as fh:
            temporary = Path(fh.name)
            fh.write(text)
        try:
            os.replace(temporary, paths.CONFIG)
        finally:
            temporary.unlink(missing_ok=True)
    config.load.cache_clear()
    config.channels.cache_clear()
    connectors.capabilities.cache_clear()
    return report
