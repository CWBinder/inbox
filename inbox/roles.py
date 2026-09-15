"""Discover roster roles and load their instructions for headless sessions.
Prefer installed prompts (which include skills), falling back to roster show.
"""
import json
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path


class RoleError(ValueError):
    pass


def available() -> dict[str, str]:
    """Discover the person's roles through roster's machine-readable catalog."""
    if not shutil.which("roster"):
        raise RoleError("Roles are unavailable: roster is not on PATH.")
    try:
        res = subprocess.run(["roster", "list", "roles", "--json"], capture_output=True,
                             text=True, timeout=10, check=True)
        rows = json.loads(res.stdout)["roles"]
        return {row["name"]: str(row.get("description") or "") for row in rows}
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError) as e:
        raise RoleError("Could not load roles from roster. Saved chats are still available with 'chats'.") from e


@lru_cache(maxsize=None)
def system_prompt(role: str) -> str:
    if not role or not shutil.which("roster"):
        return ""
    try:
        res = subprocess.run(["roster", "path", role], capture_output=True, text=True, timeout=10)
        f = Path(res.stdout.strip()) if res.returncode == 0 and res.stdout.strip() else None
        if f and f.is_file():
            text = f.read_text(encoding="utf-8")
        else:
            res = subprocess.run(["roster", "show", role], capture_output=True, text=True, timeout=10)
            if res.returncode != 0 or not res.stdout.strip():
                return ""
            # Keep the source metadata: its skills are not embedded as in an
            # installed prompt. The agent can retrieve them using roster.
            return ("Follow this roster role definition. Before doing work, read the instructions for "
                    "each skill named in its skills field using `roster show-skill NAME`.\n\n" + res.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return ""
    if text.startswith("---"):
        parts = text.split("---", 2)
        text = parts[2] if len(parts) == 3 else text
    return text.strip()
