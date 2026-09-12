"""inbox: your channels, with rules. Mail and chat through standalone client
commands (connectors), one merged view, a policy on what may be sent, reminders
that reach your phone, and a log of everything sent."""
import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from . import __version__, config, connectors, log, paths, policy, reminders, when

CONTRACT = ("--via", "--body", "--reply-to", "--attach", "--confirmed", "--json")


# ---- init / status / channels ------------------------------------------------

def cmd_init(a):
    old = Path.home() / ".pa"
    if old.is_dir() and not paths.HOME.exists():
        shutil.move(str(old), str(paths.HOME))
        print(f"moved {old} to {paths.HOME}; rewrite config.toml in the channels form (inbox init prints the example)")
    paths.HOME.mkdir(parents=True, exist_ok=True)
    for sub in (paths.REMINDERS, paths.STATE, paths.LOG):
        sub.mkdir(exist_ok=True)
    written = []
    for name, target in (("config.toml", paths.CONFIG), ("policy.toml", paths.POLICY)):
        if target.exists() and not a.force:
            continue
        shutil.copy(paths.EXAMPLES / name, target)
        written.append(target)
    if written:
        print("wrote " + ", ".join(str(w) for w in written))
        print("edit config.toml: your channels (one per account of each connector), and policy.toml: what may be sent.")
    else:
        print(f"{paths.HOME} already set up (use --force to overwrite config and policy with the examples)")


def cmd_status(a):
    ok = True
    print(f"inbox {__version__}  home {paths.HOME}")
    print(f"config     {'present' if paths.CONFIG.is_file() else 'MISSING (inbox init)'}")
    print(f"policy     {'present' if paths.POLICY.is_file() else 'missing: everything at the most restrictive level'}")
    print(f"remind     timer {'installed' if reminders.timer_installed() else 'not installed (inbox remind install)'}")
    print()
    for name in config.connectors():
        cmd = config.connector_command(name)
        if not shutil.which(cmd):
            print(f"{name:<10} NOT on PATH ({cmd})"); ok = False
            continue
        try:
            good, accounts, err, _ = connectors.run(config.channels_of(name)[0], "accounts")
        except (IndexError, connectors.ConnectorError) as e:
            print(f"{name:<10} {e}"); ok = False
            continue
        by_name = {acc.get("name"): acc for acc in (accounts or [])} if isinstance(accounts, list) else {}
        for ch in config.channels_of(name):
            acc = by_name.get(ch.account)
            if acc is None:
                print(f"{ch.name:<10} {name}:{ch.account:<9} UNKNOWN account"); ok = False
                continue
            state = "ok" if acc.get("ok") else "FAILED"
            extra = acc.get("error") or acc.get("address") or ""
            flag = " (default)" if ch.default else ""
            print(f"{ch.name:<10} {name}:{ch.account:<9} {state:<7} {extra}{flag}")
            ok = ok and bool(acc.get("ok"))
    sys.exit(0 if ok else 1)


def cmd_connectors(a):
    if a.check:
        for item, status in connectors.check(a.check):
            print(f"{item:<40} {status}")
        return
    for name, spec in config.connectors().items():
        cmd = config.connector_command(name)
        present = bool(shutil.which(cmd))
        try:
            caps = connectors.capabilities(name) if present else {}
        except connectors.ConnectorError:
            caps = {}
        alias = f"alias {spec['alias']}" if spec.get("alias") else ""
        chs = ", ".join(c.name for c in config.channels_of(name)) or "no channels"
        ver = caps.get("version", "?")
        print(f"{name:<10} {'ok' if caps else 'MISSING':<8} {cmd} {ver:<7} {alias:<12} channels: {chs}")


def cmd_channel(a):
    if a.channel_command == "add":
        text = paths.CONFIG.read_text(encoding="utf-8") if paths.CONFIG.is_file() else ""
        if f"[channels.{a.name}]" in text and not a.force:
            raise SystemExit(f"channel '{a.name}' exists (use --force to replace)")
        import re
        text = re.sub(rf"\[channels\.{re.escape(a.name)}\]\n(?:[^\[\n][^\n]*\n)*", "", text)
        block = f"\n[channels.{a.name}]\nconnector = {json.dumps(a.connector)}\naccount = {json.dumps(a.account)}\n"
        if a.default:
            block += "default = true\n"
        if a.address:
            block += f"address = {json.dumps(a.address)}\n"
        paths.CONFIG.write_text(text.rstrip() + "\n" + block, encoding="utf-8")
        print(f"channel '{a.name}' -> {a.connector}:{a.account}")
        return
    for ch in config.channels().values():
        print(f"{ch.name:<10} {ch.connector}:{ch.account:<10} {'default' if ch.default else '':<8} {ch.address or ''}")


# ---- recipients --------------------------------------------------------------

def _looks_like(who: str) -> str | None:
    """Which kind of address a raw recipient is: 'mail', 'phone', or None."""
    if "@" in who and not who.endswith(("@lid", "@g.us", "@s.whatsapp.net")):
        return "mail"
    digits = who.replace("+", "").replace(" ", "")
    if digits.isdigit() and len(digits) >= 7:
        return "phone"
    if who.endswith(("@lid", "@g.us", "@s.whatsapp.net")):
        return "phone"
    return None


def _resolve_recipient(who: str, via: str | None) -> tuple[config.Channel, str]:
    """(channel, canonical address) for a recipient. A channel name means that
    channel's own address; a raw address implies its connector's default
    channel; a name is asked of each connector in turn."""
    chs = config.channels()
    if who in chs and chs[who].address:
        target_addr = chs[who].address
        if via:
            return config.channel(via), target_addr
        return config.default_channel(chs[who].connector), target_addr
    if via:
        ch = config.channel(via)
        res = connectors.resolve(ch, who)
        if not res:
            raise SystemExit(f"'{who}' is not known on channel {via}")
        return ch, res["address"]
    kind = _looks_like(who)
    hits = []
    for name in config.connectors():
        feats = connectors.capabilities(name).get("features", {})
        if kind == "mail" and not feats.get("subject"):
            continue
        if kind == "phone" and feats.get("subject"):
            continue
        try:
            ch = config.default_channel(name)
        except config.ConfigError:
            continue
        res = connectors.resolve(ch, who)
        if res:
            hits.append((ch, res["address"], res.get("name") or who))
    if len(hits) == 1:
        return hits[0][0], hits[0][1]
    if not hits:
        raise SystemExit(f"nobody called '{who}' on any channel; pass a raw address or --via CHANNEL")
    listing = "\n  ".join(f"--via {ch.name}: {name} <{addr}>" for ch, addr, name in hits)
    raise SystemExit(f"'{who}' matches on several channels; say which:\n  {listing}")


def cmd_resolve(a):
    ch, addr = _resolve_recipient(a.who, a.via)
    print(f"{addr}  via {ch.name} ({ch.connector})")


# ---- cross-channel reads -----------------------------------------------------

def _channels_for(via: str | None) -> list[config.Channel]:
    if not via:
        return list(config.channels().values())
    return [config.channel(v.strip()) for v in via.split(",") if v.strip()]


def _line(r: dict) -> str:
    when_ = r.get("when", "")[:16].replace("T", " ")
    who = r.get("from_name") or r.get("from") or "?"
    head = r.get("subject") or r.get("text", "").replace("\n", " ")
    thread = f" [{r['thread_name']}]" if r.get("group") and r.get("thread_name") else ""
    flag = "*" if r.get("unread") else " "
    return f"{when_}  {flag} {r.get('channel', ''):<9} {who[:24]:<24}{thread} {head[:70]}    <{r.get('id')}>"


def _print_records(rows: list[dict], as_json: bool):
    if as_json:
        print(json.dumps(rows, ensure_ascii=False, indent=2)); return
    if not rows:
        print("nothing"); return
    for r in sorted(rows, key=lambda r: r.get("when", ""), reverse=True):
        print(_line(r))


def _note(e, explicit: bool):
    """A channel that cannot answer is a note when the person named it, silence otherwise."""
    if explicit:
        print(f"note: {e}", file=sys.stderr)


def cmd_search(a):
    rows = []
    for ch in _channels_for(a.via):
        args = ([a.query] if a.query else []) + ["-n", str(a.max)] + (["--since", a.since] if a.since else [])
        try:
            rows += connectors.records(ch, "search", *args)
        except connectors.ConnectorError as e:
            _note(e, bool(a.via))
    _print_records(rows, a.json)


def cmd_recent(a):
    rows = []
    for ch in _channels_for(a.via):
        try:
            rows += connectors.records(ch, "search", "-n", str(a.max), "--since", a.since)
        except connectors.ConnectorError as e:
            _note(e, bool(a.via))
    if a.unread:
        rows = [r for r in rows if r.get("unread") or r.get("unread") is None and r.get("from") != "me"]
    if a.incoming:
        rows = [r for r in rows if r.get("from") != "me"]
    _print_records(rows, a.json)


def cmd_read(a):
    """A message id needs --via; a person's name is read across channels."""
    if a.via and _looks_like(a.what) is None and len(a.what) > 12 and a.what.isalnum():
        ch = config.channel(a.via)
        rows = connectors.records(ch, "read", a.what, *(["--thread"] if a.thread else []))
        _print_records(rows, a.json); return
    rows = []
    for ch in _channels_for(a.via):
        feats = connectors.capabilities(ch.connector).get("features", {})
        try:
            res = connectors.resolve(ch, a.what)
            if not res:
                continue
            if feats.get("subject"):
                rows += connectors.records(ch, "search", f"from:{res['address']} OR to:{res['address']}", "-n", str(a.max))
            else:
                rows += connectors.records(ch, "read", a.what, "-n", str(a.max))
        except connectors.ConnectorError as e:
            _note(e, bool(a.via))
    _print_records(rows, a.json)


# ---- writes ------------------------------------------------------------------

def _split_extras(argv: list[str]) -> tuple[dict, list[str]]:
    """Contract flags for inbox, everything else for the connector, untouched."""
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--via"); p.add_argument("--body"); p.add_argument("--reply-to"); p.add_argument("--attach")
    p.add_argument("--confirmed", action="store_true"); p.add_argument("--json", action="store_true")
    known, extras = p.parse_known_args(argv)
    return vars(known), extras


def cmd_send(a):
    known, extras = _split_extras(a.rest)
    ch, addr = _resolve_recipient(a.who, known["via"])
    verdict = policy.send(ch, addr, known["confirmed"])
    if not verdict.allowed:
        log.record("send", channel=ch.name, recipient=addr, ok=False, detail=verdict.reason)
        print(f"refused: {verdict.reason}", file=sys.stderr); sys.exit(3)
    body = known["body"] if known["body"] is not None else sys.stdin.read()
    args = [addr, "--body", body]
    if known["reply_to"]:
        args += ["--reply-to", known["reply_to"]]
    if known["attach"]:
        if not connectors.capabilities(ch.connector).get("features", {}).get("attach"):
            raise SystemExit(f"channel {ch.name} cannot attach files")
        args += ["--attach", known["attach"]]
    ok, res, err, code = connectors.run(ch, "send", *args, *extras, env=connectors.send_env(ch.connector))
    log.record("send", channel=ch.name, recipient=addr, ok=ok, detail=body[:200], result=(json.dumps(res) if res else err)[:200],
               confirmed=known["confirmed"])
    if known["json"]:
        print(json.dumps(res or {"ok": ok, "reason": err}, ensure_ascii=False, indent=2))
    else:
        print(f"sent via {ch.name} to {addr}" + (f" (id {res.get('id')})" if res and res.get("id") else "") if ok else f"FAILED via {ch.name}: {err}")
    sys.exit(0 if ok else (code or 1))


def cmd_draft(a):
    known, extras = _split_extras(a.rest)
    ch, addr = _resolve_recipient(a.who, known["via"])
    if not connectors.supports(ch.connector, "draft"):
        raise SystemExit(f"channel {ch.name} ({ch.connector}) has no drafts")
    verdict = policy.draft(ch)
    if not verdict.allowed:
        print(f"refused: {verdict.reason}", file=sys.stderr); sys.exit(3)
    body = known["body"] if known["body"] is not None else sys.stdin.read()
    args = ["--to", addr, "--body", body]
    if known["reply_to"]:
        args += ["--reply-to", known["reply_to"]]
    if known["attach"]:
        args += ["--attach", known["attach"]]
    ok, res, err, code = connectors.run(ch, "draft", *args, *extras)
    log.record("draft", channel=ch.name, recipient=addr, ok=ok, detail=body[:200], result=(json.dumps(res) if res else err)[:200])
    if known["json"]:
        print(json.dumps(res or {"ok": ok, "reason": err}, ensure_ascii=False, indent=2))
    else:
        print(f"draft via {ch.name} to {addr}" + (f": {res.get('draft')}" if res and res.get("draft") else "") if ok else f"FAILED: {err}")
    sys.exit(0 if ok else (code or 1))


# ---- pass-through: inbox <connector-or-alias> [--via CH] SUB ... -------------

SEND_VERBS = {"send", "send-file", "draft-send"}
DESTRUCTIVE_VERBS = {"trash": "trash", "draft-delete": "draft-delete"}
LOGGED_VERBS = {"draft", "download", "attachments"}


def cmd_passthrough(a):
    connector = config.alias_to_connector(a.group)
    rest = list(a.rest)
    via = a.via
    if "--via" in rest:                                   # accept it anywhere
        i = rest.index("--via")
        if i + 1 < len(rest):
            via = rest[i + 1]
        del rest[i:i + 2]
    if not rest or rest[0].startswith("-"):
        caps = connectors.capabilities(connector)
        print(f"usage: inbox {a.group} [--via CHANNEL] SUBCOMMAND [ARGS...]", file=sys.stderr)
        print("subcommands: " + ", ".join(caps.get("verbs", []) + caps.get("optional", [])) +
              f"   ({config.connector_command(connector)} SUBCOMMAND -h for flags)", file=sys.stderr)
        sys.exit(2)
    sub, args = rest[0], rest[1:]
    confirmed = "--confirmed" in args
    args = [x for x in args if x != "--confirmed"]
    ch = config.resolve_via(via, connector)
    if sub in SEND_VERBS:
        who = next((x for x in args if not x.startswith("-")), "?")
        verdict = policy.send(ch, who, confirmed)
    elif sub in DESTRUCTIVE_VERBS:
        verdict = policy.destructive(ch, confirmed, sub)
    else:
        verdict = None
    if verdict is not None and not verdict.allowed:
        log.record(sub, channel=ch.name, ok=False, detail=verdict.reason + " | " + " ".join(args)[:200])
        print(f"refused: {verdict.reason}", file=sys.stderr); sys.exit(3)
    env = connectors.send_env(ch.connector) if sub in SEND_VERBS else {}
    code = connectors.passthrough(ch, sub, *args, env=env)
    if sub in SEND_VERBS | set(DESTRUCTIVE_VERBS) | LOGGED_VERBS:
        log.record(sub, channel=ch.name, ok=code == 0, detail=" ".join(args)[:200], confirmed=confirmed)
    sys.exit(code)


# ---- reminders ---------------------------------------------------------------

def _fmt_reminder(r):
    flag = {"pending": " ", "snoozed": "z", "sent": ">", "done": "x"}.get(r.status, "?")
    refs = ("  " + " ".join(r.refs)) if r.refs else ""
    return f"[{flag}] {r.id:<14} {when.fmt(r.due_dt):<17} {r.text}{refs}"


def cmd_remind(a):
    if a.remind_command == "add":
        try:
            due = when.parse(a.due)
        except when.WhenError as e:
            raise SystemExit(str(e))
        r = reminders.add(" ".join(a.text), due, a.ref or [])
        print(_fmt_reminder(r))
    elif a.remind_command == "list":
        horizon = None
        if a.due_within:
            horizon = when.parse("in " + a.due_within) if a.due_within[0].isdigit() else when.parse(a.due_within)
        rows = [r for r in reminders.all_reminders() if a.all or r.status in ("pending", "snoozed", "sent")]
        rows += reminders.ws_due_tasks(within=(horizon - when._now()) if horizon else None)
        if horizon:
            rows = [r for r in rows if r.due_dt <= horizon]
        if a.json:
            print(json.dumps([r.__dict__ for r in rows], ensure_ascii=False, indent=2, default=str)); return
        if not rows:
            print("nothing due" if horizon else "no reminders"); return
        for r in sorted(rows, key=lambda r: r.due):
            print(_fmt_reminder(r))
    elif a.remind_command == "run":
        report = reminders.run(dry_run=a.dry_run)
        print("\n".join(report) if report else "nothing due")
    elif a.remind_command == "done":
        print(reminders.mark_done(a.id))
    elif a.remind_command == "snooze":
        try:
            until = when.parse(a.until)
        except when.WhenError as e:
            raise SystemExit(str(e))
        print(reminders.snooze(a.id, until))
    elif a.remind_command == "install":
        print(reminders.install_timer(a.every))
    elif a.remind_command == "uninstall":
        print(reminders.uninstall_timer())
    elif a.remind_command == "show":
        r = reminders.get(a.id)
        print(json.dumps(r.__dict__, ensure_ascii=False, indent=2))
        print("--- as it would be sent ---")
        print(reminders.render(r))


# ---- policy / log ------------------------------------------------------------

def cmd_policy(a):
    if not paths.POLICY.is_file():
        print(f"no policy file at {paths.POLICY}: everything at the most restrictive level"); return
    print(paths.POLICY.read_text().rstrip())


def cmd_log(a):
    since = log.parse_since(a.since) if a.since else None
    rows = log.entries(since)
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2)); return
    if not rows:
        print("no entries"); return
    for e in rows:
        to = f" -> {e['recipient']}" if e.get("recipient") else ""
        mark = "ok " if e.get("ok") else "REFUSED" if "policy" in (e.get("detail") or "") else "FAIL"
        print(f"{e['ts'][:16]}  {mark:<7} {e.get('channel', ''):<9} {e['action']:<10}{to}  {e.get('detail', '')[:80]}")


# ---- parser ------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(prog="inbox", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog="""where: --via CHANNEL names one of your channels (inbox channel list).
recipients: a channel name (me), a raw address (x@y.org, 4366...), or a contact name the connectors resolve.

examples:
  inbox recent --since 24h --incoming            everything that came in, all channels
  inbox search invoice --via qmt,personal
  inbox read BJ                                  one person, across channels
  inbox send BJ --body "See you Saturday" --confirmed
  inbox draft x@y.org --via qmt --subject Hi --body "..."
  inbox wa read BJ -n 30 | inbox email search "is:unread"      a connector's own commands, account chosen for you
  inbox remind add pay the fee --due fri 9am --ref url:https://...""")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("init", help="create ~/.inbox with example config and policy"); s.add_argument("--force", action="store_true"); s.set_defaults(func=cmd_init)
    s = sub.add_parser("status", help="every channel and connector in one check"); s.set_defaults(func=cmd_status)
    s = sub.add_parser("connectors", help="the client commands inbox talks to; --check NAME runs the conformance test")
    s.add_argument("--check", metavar="CONNECTOR"); s.set_defaults(func=cmd_connectors)

    s = sub.add_parser("channel", help="your channels: list, or add NAME --connector X --account Y")
    cs = s.add_subparsers(dest="channel_command")
    c = cs.add_parser("add"); c.add_argument("name"); c.add_argument("--connector", required=True); c.add_argument("--account", required=True)
    c.add_argument("--default", action="store_true"); c.add_argument("--address"); c.add_argument("--force", action="store_true")
    cs.add_parser("list")
    s.set_defaults(func=cmd_channel, channel_command=None)

    s = sub.add_parser("search", help="messages matching a query, across channels"); s.add_argument("query", nargs="?")
    s.add_argument("--via", help="channel or comma list; default all"); s.add_argument("--since"); s.add_argument("-n", "--max", type=int, default=10)
    s.add_argument("--json", action="store_true"); s.set_defaults(func=cmd_search)
    s = sub.add_parser("recent", help="what came in lately, merged by time"); s.add_argument("--since", default="24h")
    s.add_argument("--via"); s.add_argument("-n", "--max", type=int, default=30); s.add_argument("--unread", action="store_true")
    s.add_argument("--incoming", action="store_true", help="hide your own messages"); s.add_argument("--json", action="store_true"); s.set_defaults(func=cmd_recent)
    s = sub.add_parser("read", help="one person across channels, or one message id with --via"); s.add_argument("what")
    s.add_argument("--via"); s.add_argument("--thread", action="store_true"); s.add_argument("-n", "--max", type=int, default=20)
    s.add_argument("--json", action="store_true"); s.set_defaults(func=cmd_read)
    s = sub.add_parser("resolve", help="which channel and address a recipient resolves to"); s.add_argument("who"); s.add_argument("--via"); s.set_defaults(func=cmd_resolve)

    s = sub.add_parser("send", help="send WHO [--via CH] [--body T] [--reply-to ID] [--attach F] [--confirmed] [connector flags...]",
                       usage="inbox send WHO [--via CHANNEL] [--body TEXT] [--reply-to ID] [--attach FILE] [--confirmed] [connector flags...]")
    s.add_argument("who"); s.add_argument("rest", nargs=argparse.REMAINDER); s.set_defaults(func=cmd_send)
    s = sub.add_parser("draft", help="draft WHO [--via CH] [--body T] ... on a channel that has drafts",
                       usage="inbox draft WHO [--via CHANNEL] [--body TEXT] [--reply-to ID] [--attach FILE] [connector flags...]")
    s.add_argument("who"); s.add_argument("rest", nargs=argparse.REMAINDER); s.set_defaults(func=cmd_draft)

    try:
        for name, spec in config.connectors().items():
            for word in {name, spec.get("alias")} - {None}:
                s = sub.add_parser(word, help=f"{name}'s own commands, account chosen for you: inbox {word} [--via CH] SUB ...",
                                   usage=f"inbox {word} [--via CHANNEL] SUBCOMMAND [ARGS...]")
                s.add_argument("--via", metavar="CHANNEL"); s.add_argument("rest", nargs=argparse.REMAINDER)
                s.set_defaults(func=cmd_passthrough, group=word)
    except config.ConfigError:
        pass

    s = sub.add_parser("remind", help="reminders: add, list, run, done, snooze, install")
    rs = s.add_subparsers(dest="remind_command", required=True)
    r = rs.add_parser("add"); r.add_argument("text", nargs="+"); r.add_argument("--due", required=True); r.add_argument("--ref", action="append")
    r = rs.add_parser("list"); r.add_argument("--due-within"); r.add_argument("--all", action="store_true"); r.add_argument("--json", action="store_true")
    r = rs.add_parser("run"); r.add_argument("--dry-run", action="store_true")
    r = rs.add_parser("done"); r.add_argument("id")
    r = rs.add_parser("snooze"); r.add_argument("id"); r.add_argument("--until", required=True)
    r = rs.add_parser("show"); r.add_argument("id")
    r = rs.add_parser("install"); r.add_argument("--every", type=int, default=10)
    rs.add_parser("uninstall")
    s.set_defaults(func=cmd_remind)

    s = sub.add_parser("policy", help="show the send rules"); s.set_defaults(func=cmd_policy)
    s = sub.add_parser("log", help="everything sent, drafted, saved or refused"); s.add_argument("--since"); s.add_argument("--json", action="store_true"); s.set_defaults(func=cmd_log)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except BrokenPipeError:
        pass
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
