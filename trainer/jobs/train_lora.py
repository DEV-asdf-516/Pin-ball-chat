# Prepare chat data and delegate LoRA training to mlx-lm.

from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT: Path = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trainer.domain.datasets import DatasetError, data_path, validate_name
from trainer.domain.recipes import load_recipe, recipe_path
from trainer.domain.runs import run_meta_path
from trainer.domain.training_runs import validate_training_inputs
from trainer.util import trainer_root, utc_now

log = logging.getLogger(__name__)


def git_commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], 
            cwd=ROOT, 
            text=True, 
            capture_output=True, 
            check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def read_dataset_rows(manifests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for manifest in manifests:
        with data_path(manifest["name"]).open("r", encoding="utf-8") as handle:
            rows.extend(json.loads(line) for line in handle if line.strip())

    if not rows:
        raise DatasetError("training datasets contain no rows")

    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    parser: argparse.ArgumentParser = argparse.ArgumentParser()
    parser.add_argument("--datasets", required=True, nargs="+")
    parser.add_argument("--recipe", required=True)
    parser.add_argument("--output-name", required=True)
    args: argparse.Namespace = parser.parse_args()
    
    try:
        output_name: str = validate_name(args.output_name)
        manifests: list[dict[str, Any]] = validate_training_inputs(args.datasets, args.recipe)
        recipe: dict[str, Any] = load_recipe(args.recipe)
        recipe_file: Path = recipe_path(args.recipe)

        rows: list[dict[str, Any]] = read_dataset_rows(manifests)
        run_dir: Path = trainer_root() / "runs" / output_name
       
        if run_dir.exists():
            raise DatasetError("run output directory already exists")
        
        data_dir: Path = run_dir / "data"
        data_dir.mkdir(parents=True)
        
        valid_count: int = max(1, round(len(rows) * 0.05))
        valid_rows: list[dict[str, Any]] = rows[-valid_count:]
        train_rows: list[dict[str, Any]] = rows[:-valid_count]
        
        write_jsonl(data_dir / "train.jsonl", train_rows)
        write_jsonl(data_dir / "valid.jsonl", valid_rows)
        
        shutil.copy2(recipe_file, run_dir / recipe_file.name)
        
        for manifest in manifests:
            source: Path = trainer_root() / "datasets" / manifest["name"] / "manifest.json"
            shutil.copy2(source, run_dir / f"manifest-{manifest['name']}.json")
        
        training: dict[str, Any] = recipe.get("training", {})
        
        lora: dict[str, Any] = recipe.get("lora", {})
        
        command: list[str] = [
            "mlx_lm.lora",
            "--model", recipe["base_model"],
            "--train",
            "--data", str(data_dir),
            "--adapter-path", str(run_dir / "adapters"),
            "--iters", str(training["iters"]),
            "--batch-size", str(training["batch_size"]),
            "--learning-rate", str(training["learning_rate"]),
            "--max-seq-length", str(training["max_seq_length"]),
            "--num-layers", str(training["num_layers"]),
            "--lora-parameters", json.dumps({"rank": lora["rank"], "alpha": lora["alpha"], "dropout": lora["dropout"]}),
        ]
        
        if training.get("grad_checkpoint"):
            command.append("--grad-checkpoint")

        meta: dict[str, Any] = {
            "datasets": args.datasets,
            "recipe": args.recipe,
            "backend": recipe["backend"],
            "base_model": recipe["base_model"],
            "row_count": len(rows),
            "train_rows": len(train_rows),
            "valid_rows": len(valid_rows),
            "created_at": utc_now(),
            "git_commit": git_commit(),
        }
        
        meta_path: Path = run_meta_path(run_dir)
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        
        subprocess.run(command, check=True)
    
    except (DatasetError, KeyError, json.JSONDecodeError, OSError, subprocess.CalledProcessError) as exc:
        log.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
