"""Resume an exposed local Codex session and return only its final response."""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def command() -> str | None:
    binary = shutil.which("codex")
    if binary:
        return binary
    # launchd does not inherit the desktop app's PATH.
    for app in ("ChatGPT", "Codex"):
        binary = Path(f"/Applications/{app}.app/Contents/Resources/codex")
        if binary.is_file() and os.access(binary, os.X_OK):
            return str(binary)
    return None


def turn(session: str | None, prompt: str, *, cwd: str | None = None,
         dry_run: bool = False) -> tuple[bool, str]:
    if not session:
        return False, "this Codex conversation has no exposed session"
    binary = command()
    if not binary:
        return False, "Codex CLI is not available"
    if dry_run:
        return True, f"would resume Codex session {session} with: {prompt[:80]}"
    phone_prompt = ("This message is from the user through their Inbox Telegram bridge. "
                    "Your final response is delivered to their phone. Keep it concise.\n\n" + prompt)
    try:
        with tempfile.TemporaryDirectory(prefix="inbox-codex-") as tmp:
            output = Path(tmp) / "answer.txt"
            # Use the existing account and permission configuration. No sandbox
            # bypass or model override. Stdin preserves arbitrary message text.
            argv = [binary, "exec", "resume", session, "--output-last-message", str(output), "-"]
            proc = subprocess.run(argv, input=phone_prompt, capture_output=True, text=True,
                                  timeout=900, cwd=cwd)
            answer = output.read_text(encoding="utf-8").strip() if output.is_file() else ""
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"could not run Codex: {e}"
    if proc.returncode != 0:
        return False, proc.stderr.strip()[-400:] or "Codex could not resume this session"
    if not answer:
        return False, "Codex returned no final response"
    return True, answer
