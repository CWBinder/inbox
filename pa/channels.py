"""The standalone clients pa drives. Each is a command on PATH; pa adds the
account or identity and passes everything else through untouched."""
import os
import shutil
import subprocess

from . import config


def _run(argv: list[str], capture: bool = False) -> subprocess.CompletedProcess:
    if not shutil.which(argv[0]):
        raise SystemExit(f"'{argv[0]}' is not on PATH; install it first")
    return subprocess.run(argv, text=True, capture_output=capture)


# ---- whatsapp ----------------------------------------------------------------

def whatsapp_argv(identity: str | None, *args: str) -> tuple[str, list[str]]:
    name, profile = config.whatsapp_identity(identity)
    return name, ["whatsapp", "--profile", profile, *args]


def whatsapp(identity: str | None, *args: str, capture: bool = False, allow_send: bool = False):
    name, argv = whatsapp_argv(identity, *args)
    env = os.environ.copy()
    if allow_send:
        env["WHATSAPP_ALLOW_SEND"] = "1"     # pa's policy is the gate; the client's own switch stays as it is
    if not shutil.which(argv[0]):
        raise SystemExit("'whatsapp' is not on PATH; install the WhatsApp client first")
    return name, subprocess.run(argv, text=True, capture_output=capture, env=env)


# ---- email -------------------------------------------------------------------

def email_argv(account: str | None, *args: str) -> tuple[str, list[str]]:
    name = config.email_account(account)
    backend = config.load().get("email", {}).get("backend", "gmail")
    if backend == "gmail":
        return name, ["gmail", *args, "--account", name]
    if backend == "ws":                                   # the pre-split spelling
        return name, ["ws", "email", *args, "--account", name]
    raise SystemExit(f"unknown email backend '{backend}' in config (gmail or ws)")


def email(account: str | None, *args: str, capture: bool = False):
    name, argv = email_argv(account, *args)
    return name, _run(argv, capture=capture)
