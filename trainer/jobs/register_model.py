# Register a quantized trainer run with the local Ollama server.

from __future__ import annotations

import argparse
import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    parser: argparse.ArgumentParser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True, type=Path)
    args: argparse.Namespace = parser.parse_args()
    run_dir: Path = args.run_dir.resolve()
    
    try:
        gguf: Path = run_dir / "model-q4_K_M.gguf"
        if not gguf.is_file():
            raise RuntimeError("run export_gguf.py first")
        
        output_name: str = run_dir.name
        
        template: str = subprocess.run(
            ["ollama", "show", "gemma4:latest", "--template"], 
            text=True, 
            capture_output=True, 
            check=True
        ).stdout
        
        modelfile: Path = run_dir / "Modelfile"
        modelfile.write_text(f"FROM {gguf}\nTEMPLATE \"\"\"\n{template.rstrip()}\n\"\"\"\n", encoding="utf-8")
        
        subprocess.run(["ollama", "create", output_name, "-f", str(modelfile)], check=True)
        
        registered: dict[str, Any] = {
            "model": output_name,
            "created_at": now(),
            "gguf_size": gguf.stat().st_size,
        }

        registered_path: Path = run_dir / "registered.json"
        registered_path.write_text(json.dumps(registered, indent=2) + "\n", encoding="utf-8")
        
    except (OSError, KeyError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        log.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
