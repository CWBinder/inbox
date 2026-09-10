"""pa: the assistant. Mail and WhatsApp through standalone clients, reminders,
a policy on what may be sent, and a log of everything sent."""
import argparse
import json
import shutil
import subprocess
import sys

from . import __version__, channels, config, log, paths, policy, reminders, when


# ---- init / status -----------------------------------------------------------

def cmd_init(a):
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
        print("edit config.toml with your accounts and identities, and policy.toml with what may be sent.")
    else:
        print(f"{paths.HOME} already set up (use --force to overwrite config and policy with the examples)")


def cmd_status(a):
    ok = True
    print(f"pa {__version__}  home {paths.HOME}")
    print(f"config     {'present' if paths.CONFIG.is_file() else 'MISSING (pa init)'}")
    print(f"policy     {'present' if paths.POLICY.is_file() else 'missing: everything defaults to the most restrictive level'}")
    for cmd in ("whatsapp", "ws"):
        print(f"{cmd:<10} {'on PATH' if shutil.which(cmd) else 'NOT on PATH'}")
    print()
    for ident, spec in config.whatsapp_identities().items():
        r = subprocess.run(["whatsapp", "--profile", str(spec.get("profile", "default")), "bridge", "status", "--json"],
                           capture_output=True, text=True)
        try:
            s = json.loads(r.stdout)
            link = {True: "linked", False: "NOT LINKED", None: "no store yet"}[s.get("linked")]
            run = "running" if s.get("running") else "not running"
            print(f"whatsapp:{ident:<9} {run:<12} {link:<13} port {s.get('port')}  launchd {'yes' if s.get('launchd_installed') else 'no'}")
            ok = ok and s.get("running") and s.get("linked")
        except (json.JSONDecodeError, KeyError):
            print(f"whatsapp:{ident:<9} status failed: {r.stderr.strip() or r.stdout.strip()}")
            ok = False
    print(f"remind     timer {'installed' if reminders.timer_installed() else 'not installed (pa remind install)'}")
    if config.email_accounts():
        r = subprocess.run(["ws", "email", "accounts"], capture_output=True, text=True)
        for line in (r.stdout + r.stderr).splitlines():
            if line.startswith(("ok:", "failed:")):
                print(f"email      {line}")
                ok = ok and line.startswith("ok:")
    sys.exit(0 if ok else 1)


# ---- whatsapp ----------------------------------------------------------------

def cmd_wa(a):
    rest = list(a.args)
    sub = rest[0] if rest else None
    if sub in ("send", "send-file"):
        return _wa_send(a, sub, rest[1:])
    _, r = channels.whatsapp(a.identity, *rest)
    if sub == "download" and r.returncode == 0:
        log.record("download", channel="whatsapp", identity=a.identity or config.whatsapp_default(), ok=True, detail=" ".join(rest[1:]))
    sys.exit(r.returncode)


def _wa_send(a, sub, rest):
    p = argparse.ArgumentParser(prog=f"pa wa {sub}", add_help=True)
    p.add_argument("who")
    if sub == "send":
        p.add_argument("--body", default=None, help="text; omitted means read stdin")
    else:
        p.add_argument("path")
        p.add_argument("--voice", action="store_true")
    p.add_argument("--as-phone", action="store_true")
    p.add_argument("--confirmed", action="store_true",
                   help="the person approved this exact recipient and text (required where policy says 'confirm')")
    s = p.parse_args(rest)
    identity, _ = config.whatsapp_identity(a.identity)
    verdict = policy.whatsapp_send(identity, s.who, s.confirmed)
    if not verdict.allowed:
        log.record(sub, channel="whatsapp", identity=identity, recipient=s.who, ok=False, detail=verdict.reason)
        print(f"refused: {verdict.reason}", file=sys.stderr)
        sys.exit(3)
    body = s.body if sub == "send" else None
    if sub == "send" and body is None:
        body = sys.stdin.read()
    argv = [sub, s.who]
    if sub == "send":
        argv += ["--body", body]
    else:
        argv += [s.path] + (["--voice"] if s.voice else [])
    if s.as_phone:
        argv.append("--as-phone")
    _, r = channels.whatsapp(identity, *argv, capture=True, allow_send=True)
    out = (r.stdout + r.stderr).strip()
    print(out)
    log.record(sub, channel="whatsapp", identity=identity, recipient=s.who, ok=r.returncode == 0,
               detail=(body or s.path)[:200], result=out[:200], confirmed=s.confirmed)
    sys.exit(r.returncode)


# ---- email -------------------------------------------------------------------

_EMAIL_SEND = ("send", "draft-send")
_EMAIL_DESTRUCTIVE = {"trash": "trash", "draft-delete": "draft-delete"}


def cmd_email(a):
    rest = list(a.args)
    sub = rest[0] if rest else None
    confirmed = "--confirmed" in rest
    rest = [x for x in rest if x != "--confirmed"]
    account = config.email_account(a.account)
    if sub in _EMAIL_SEND:
        verdict = policy.email_send(confirmed)
    elif sub in _EMAIL_DESTRUCTIVE:
        verdict = policy.email_destructive(confirmed, _EMAIL_DESTRUCTIVE[sub])
    else:
        verdict = None
    if verdict is not None and not verdict.allowed:
        log.record(sub, channel="email", identity=account, ok=False, detail=verdict.reason + " | " + " ".join(rest[1:])[:200])
        print(f"refused: {verdict.reason}", file=sys.stderr)
        sys.exit(3)
    _, r = channels.email(account, *rest)
    if sub in (*_EMAIL_SEND, *_EMAIL_DESTRUCTIVE, "draft") or (sub == "attachments" and "--save" in rest):
        log.record(sub, channel="email", identity=account, ok=r.returncode == 0,
                   recipient=_flag(rest, "--to"), detail=" ".join(rest[1:])[:200], confirmed=confirmed)
    sys.exit(r.returncode)


def _flag(argv: list[str], name: str) -> str | None:
    if name in argv:
        i = argv.index(name)
        if i + 1 < len(argv):
            return argv[i + 1]
    return None



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
        r = reminders.add(" ".join(a.text), due, a.ref or [], channel=a.channel)
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
        print(f"no policy file at {paths.POLICY}: everything at the most restrictive level")
        return
    print(paths.POLICY.read_text().rstrip())


def cmd_log(a):
    since = log.parse_since(a.since) if a.since else None
    rows = log.entries(since)
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    if not rows:
        print("no entries")
        return
    for e in rows:
        who = e.get("identity") or ""
        to = f" -> {e['recipient']}" if e.get("recipient") else ""
        mark = "ok " if e.get("ok") else "REFUSED" if "policy" in (e.get("detail") or "") else "FAIL"
        print(f"{e['ts'][:16]}  {mark:<7} {e['channel']}:{who:<9} {e['action']:<12}{to}  {e.get('detail','')[:80]}")


# ---- parser ------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(prog="pa", description=__doc__)
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("init", help="create ~/.pa with example config and policy")
    s.add_argument("--force", action="store_true", help="overwrite existing config and policy")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("status", help="every identity, account, bridge and credential in one check")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("wa", help="WhatsApp through the whatsapp client, identity chosen for you",
                       usage="pa wa [--as IDENTITY] SUBCOMMAND [ARGS...]   (whatsapp -h lists the subcommands)")
    s.add_argument("--as", dest="identity", metavar="IDENTITY", default=None,
                   help="which linked account to act as (config: [whatsapp.identities]); default from config")
    s.add_argument("args", nargs=argparse.REMAINDER, help="passed to the whatsapp client")
    s.set_defaults(func=cmd_wa)

    s = sub.add_parser("email", help="mail through the email client, account chosen for you",
                       usage="pa email [--account NAME] SUBCOMMAND [ARGS...]   (ws email -h lists the subcommands)")
    s.add_argument("--account", default=None, help="which mailbox (config: [email.accounts]); default from config")
    s.add_argument("args", nargs=argparse.REMAINDER, help="passed to the email client; add --confirmed for send/trash")
    s.set_defaults(func=cmd_email)

    s = sub.add_parser("remind", help="reminders: add, list, run the loop, done, snooze")
    rs = s.add_subparsers(dest="remind_command", required=True)
    r = rs.add_parser("add", help="new reminder: pa remind add pay the fee --due fri 9am --ref url:https://...")
    r.add_argument("text", nargs="+"); r.add_argument("--due", required=True, help="'2026-09-12 16:00', 'fri 9am', 'tomorrow 18:30', 'in 2h'")
    r.add_argument("--ref", action="append", metavar="KIND:VALUE", help="what it is about; repeatable (ws:task:x, email:qmt:<id>, url:..., file:...)")
    r.add_argument("--channel", default="whatsapp")
    r = rs.add_parser("list", help="open reminders plus due ws tasks")
    r.add_argument("--due-within", metavar="SPAN", help="e.g. 2d, 12h; only what is due by then")
    r.add_argument("--all", action="store_true", help="include done ones"); r.add_argument("--json", action="store_true")
    r = rs.add_parser("run", help="fire everything due: what a launchd timer calls")
    r.add_argument("--dry-run", action="store_true", help="show what would be sent, send nothing")
    r = rs.add_parser("done", help="close a reminder, or a ws task via its ws:<key> id"); r.add_argument("id")
    r = rs.add_parser("snooze", help="push a reminder"); r.add_argument("id"); r.add_argument("--until", required=True)
    r = rs.add_parser("show", help="one reminder and the message it would produce"); r.add_argument("id")
    r = rs.add_parser("install", help="launchd timer that runs `pa remind run` on this Mac")
    r.add_argument("--every", type=int, default=10, metavar="MINUTES")
    rs.add_parser("uninstall", help="remove the timer")
    s.set_defaults(func=cmd_remind)

    s = sub.add_parser("policy", help="show the send and confirmation rules")
    s.set_defaults(func=cmd_policy)

    s = sub.add_parser("log", help="everything sent, saved or refused on your behalf")
    s.add_argument("--since", default=None, help="7d, 24h, 30m, or an ISO date")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_log)
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
