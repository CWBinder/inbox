#!/usr/bin/env python3
"""Install this checkout in its own .venv and expose a user-local command."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import venv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bin-dir", type=Path, default=Path.home() / ".local/bin",
                        help="launcher directory (default: ~/.local/bin)")
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        parser.error("Python 3.11 or newer is required")
    if os.name == "nt":
        parser.error("this launcher installer supports macOS and Linux")

    root = Path(__file__).resolve().parent
    env = root / ".venv"
    target = env / "bin/inbox"
    link = args.bin_dir.expanduser().absolute() / "inbox"
    old_uv_target = Path.home() / ".local/share/uv/tools/inbox-cli/bin/inbox"
    owned_targets = {target, old_uv_target}

    if os.path.lexists(link) and not (link.is_symlink() and link.resolve() in owned_targets):
        parser.error(f"{link} already belongs to another installation; choose --bin-dir DIR")
    if not (env / "bin/python").exists():
        venv.EnvBuilder(with_pip=True).create(env)
    subprocess.run([str(env / "bin/python"), "-m", "pip", "install", "-e", str(root)], check=True)

    link.parent.mkdir(parents=True, exist_ok=True)
    if link.is_symlink() and link.resolve() != target:
        link.unlink()
    if not link.is_symlink():
        link.symlink_to(target)
    subprocess.run([str(link), "--help"], check=True, stdout=subprocess.DEVNULL)

    print(f"Installed: {link}\nEnvironment: {env}")
    if str(link.parent) not in os.environ.get("PATH", "").split(os.pathsep):
        print(f"Add {link.parent} to your shell PATH, then open a new terminal.")
        if link.parent == Path.home() / ".local/bin":
            print('For bash/zsh, add: export PATH="$HOME/.local/bin:$PATH"')
    print("Next: inbox init")


if __name__ == "__main__":
    main()
