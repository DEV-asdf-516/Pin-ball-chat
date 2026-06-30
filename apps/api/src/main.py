import argparse
import json
from pathlib import Path

from core.db import ROOT, connect, init_db, load_resources


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["init", "load"])
    parser.add_argument("--root", type=Path, default=None, help="content root (default: PINBALLCHAT_ROOT or project root)")
    args = parser.parse_args()
    root = args.root or ROOT
    with connect() as conn:
        init_db(conn)
        errors = load_resources(conn, root) if args.command == "load" else []
        print(json.dumps({"ok": not errors, "errors": errors}, ensure_ascii=False))


if __name__ == "__main__":
    main()
