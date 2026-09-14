"""A roster role as a headless system prompt: the installed subagent file
without its frontmatter, found through `roster path ROLE`."""
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=None)
def system_prompt(role: str) -> str:
    if not role or not shutil.which("roster"):
        return ""
    res = subprocess.run(["roster", "path", role], capture_output=True, text=True)
    if res.returncode != 0 or not res.stdout.strip():
        return ""
    f = Path(res.stdout.strip())
    if not f.is_file():
        return ""
    text = f.read_text(encoding="utf-8")
    if text.startswith("---"):
        parts = text.split("---", 2)
        text = parts[2] if len(parts) == 3 else text
    return text.strip()
