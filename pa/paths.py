"""Where pa keeps the person's things: one folder in home, never per project."""
import os
from pathlib import Path

HOME = Path(os.environ.get("PA_HOME") or Path.home() / ".pa")
CONFIG = HOME / "config.toml"
POLICY = HOME / "policy.toml"
REMINDERS = HOME / "reminders"
STATE = HOME / "state"
LOG = HOME / "log"
LOG_FILE = LOG / "actions.jsonl"

PACKAGE = Path(__file__).resolve().parent
EXAMPLES = PACKAGE / "examples"
