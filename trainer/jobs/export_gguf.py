# Fuse an MLX LoRA adapter, convert it to GGUF, and quantize it.

from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT: Path = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trainer.domain.runs import read_run_meta, run_backend
from trainer.domain.specs import Backend

log = logging.getLogger(__name__)


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    parser: argparse.ArgumentParser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True, type=Path)
    args: argparse.Namespace = parser.parse_args()
    run_dir: Path = args.run_dir.resolve()
    
    try:
        meta: dict[str, Any] = read_run_meta(run_dir)
        backend: Backend = run_backend(meta)

        if backend == Backend.CUDA:
            raise RuntimeError("cuda backend is not implemented in v0.1")
        
        llama_root_value: str | None = os.environ.get("LLAMA_CPP_DIR")
        
        if not llama_root_value:
            raise RuntimeError("LLAMA_CPP_DIR is required (llama.cpp clone with convert_hf_to_gguf.py)")
       
        llama_root: Path = Path(llama_root_value).resolve()
        
        converter: Path = llama_root / "convert_hf_to_gguf.py"
        
        quantizer: str = shutil.which("llama-quantize") or str(llama_root / "llama-quantize")
        
        if not converter.is_file() or not Path(quantizer).is_file():
            raise RuntimeError("LLAMA_CPP_DIR must contain convert_hf_to_gguf.py and llama-quantize must be installed")
        
        merged: Path = run_dir / "merged"
        f16: Path = run_dir / "model-f16.gguf"
        q4: Path = run_dir / "model-q4_K_M.gguf"
        
        subprocess.run(
            ["mlx_lm.fuse", "--model", meta["base_model"], "--adapter-path", str(run_dir / "adapters"), "--save-path", str(merged), "--de-quantize"],
            check=True,
        )
        subprocess.run([sys.executable, str(converter), str(merged), "--outfile", str(f16), "--outtype", "f16"], check=True)
        subprocess.run([str(quantizer), str(f16), str(q4), "q4_K_M"], check=True)
        
        shutil.rmtree(merged)
        
        f16.unlink()
    
    except (OSError, KeyError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        log.error("%s", exc)
        return 1
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
