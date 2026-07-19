"""Prepare chat data and delegate LoRA training to mlx-lm."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trainer.api.dataset_io import DatasetError, data_path, read_manifest, trainer_root, utc_now, validate_name


def git_commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def load_recipe(recipe_name: str) -> tuple[Path, dict[str, Any]]:
    if Path(recipe_name).name != recipe_name:
        raise DatasetError("recipe does not exist")
    path = trainer_root() / "recipes" / recipe_name
    if not path.is_file():
        raise DatasetError("recipe does not exist")
    try:
        recipe = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise DatasetError("recipe is invalid") from exc
    if not isinstance(recipe, dict) or recipe.get("backend") not in {"mlx", "cuda"}:
        raise DatasetError("recipe backend is invalid")
    return path, recipe


def read_dataset_rows(names: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    manifests: list[dict[str, Any]] = []
    for name in names:
        manifest = read_manifest(validate_name(name))
        if manifest["format"] != "chat":
            raise DatasetError("v0.1 supports chat only")
        manifests.append(manifest)
        with data_path(name).open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    rows.append(json.loads(line))
    if not rows:
        raise DatasetError("training datasets contain no rows")
    return rows, manifests


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--datasets", required=True, nargs="+")
    parser.add_argument("--recipe", required=True)
    parser.add_argument("--output-name", required=True)
    args = parser.parse_args()
    try:
        output_name = validate_name(args.output_name)
        recipe_path, recipe = load_recipe(args.recipe)
        if recipe["backend"] == "cuda":
            raise DatasetError("cuda backend is not implemented in v0.1")
        rows, manifests = read_dataset_rows(args.datasets)
        run_dir = trainer_root() / "runs" / output_name
        if run_dir.exists():
            raise DatasetError("run output directory already exists")
        data_dir = run_dir / "data"
        data_dir.mkdir(parents=True)
        valid_count = max(1, round(len(rows) * 0.05))
        valid_rows = rows[-valid_count:]
        train_rows = rows[:-valid_count]
        write_jsonl(data_dir / "train.jsonl", train_rows)
        write_jsonl(data_dir / "valid.jsonl", valid_rows)
        shutil.copy2(recipe_path, run_dir / recipe_path.name)
        for manifest in manifests:
            source = trainer_root() / "datasets" / manifest["name"] / "manifest.json"
            shutil.copy2(source, run_dir / f"manifest-{manifest['name']}.json")
        training = recipe.get("training", {})
        lora = recipe.get("lora", {})
        command = [
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
        meta = {
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
        (run_dir / "run_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        subprocess.run(command, check=True)
    except (DatasetError, KeyError, json.JSONDecodeError, yaml.YAMLError, OSError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
