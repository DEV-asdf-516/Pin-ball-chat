"""Fuse an MLX LoRA adapter, convert it to GGUF, and quantize it."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True, type=Path)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    try:
        meta = json.loads((run_dir / "run_meta.json").read_text(encoding="utf-8"))
        if meta.get("backend") == "cuda":
            raise RuntimeError("cuda backend is not implemented in v0.1")
        if meta.get("backend") != "mlx":
            raise RuntimeError("run backend is invalid")
        llama_root_value = os.environ.get("LLAMA_CPP_DIR")
        if not llama_root_value:
            raise RuntimeError("LLAMA_CPP_DIR is required (llama.cpp clone with convert_hf_to_gguf.py)")
        llama_root = Path(llama_root_value).resolve()
        converter = llama_root / "convert_hf_to_gguf.py"
        quantizer = shutil.which("llama-quantize") or str(llama_root / "llama-quantize")
        if not converter.is_file() or not Path(quantizer).is_file():
            raise RuntimeError("LLAMA_CPP_DIR must contain convert_hf_to_gguf.py and llama-quantize must be installed")
        merged = run_dir / "merged"
        f16 = run_dir / "model-f16.gguf"
        q4 = run_dir / "model-q4_K_M.gguf"
        subprocess.run(
            ["mlx_lm.fuse", "--model", meta["base_model"], "--adapter-path", str(run_dir / "adapters"), "--save-path", str(merged), "--de-quantize"],
            check=True,
        )
        subprocess.run([sys.executable, str(converter), str(merged), "--outfile", str(f16), "--outtype", "f16"], check=True)
        subprocess.run([str(quantizer), str(f16), str(q4), "q4_K_M"], check=True)
        shutil.rmtree(merged)
        f16.unlink()
    except (OSError, KeyError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
