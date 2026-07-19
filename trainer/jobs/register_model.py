"""Register a quantized trainer run with the local Ollama server."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True, type=Path)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    try:
        gguf = run_dir / "model-q4_K_M.gguf"
        if not gguf.is_file():
            raise RuntimeError("run export_gguf.py first")
        meta = json.loads((run_dir / "run_meta.json").read_text(encoding="utf-8"))
        output_name = run_dir.name
        template = subprocess.run(
            ["ollama", "show", "gemma4:latest", "--template"], text=True, capture_output=True, check=True
        ).stdout
        modelfile = run_dir / "Modelfile"
        modelfile.write_text(f"FROM {gguf}\nTEMPLATE \"\"\"\n{template.rstrip()}\n\"\"\"\n", encoding="utf-8")
        subprocess.run(["ollama", "create", output_name, "-f", str(modelfile)], check=True)
        (run_dir / "registered.json").write_text(
            json.dumps({"model": output_name, "created_at": now(), "gguf_size": gguf.stat().st_size}, indent=2) + "\n",
            encoding="utf-8",
        )
    except (OSError, KeyError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
