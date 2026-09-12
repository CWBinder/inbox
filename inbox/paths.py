"""Where inbox keeps the person's things: one folder in home, never per project."""
import os
from pathlib import Path

HOME = Path(os.environ.get("INBOX_HOME") or Path.home() / ".inbox")
CONFIG = HOME / "config.toml"
POLICY = HOME / "policy.toml"
REMINDERS = HOME / "reminders"
STATE = HOME / "state"
LOG = HOME / "log"
LOG_FILE = LOG / "actions.jsonl"

PACKAGE = Path(__file__).resolve().parent
EXAMPLES = PACKAGE / "examples"
