# Recipe file discovery and validation for training runs.

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ..util import trainer_root
from .specs import Backend, DatasetError


def recipes_dir() -> Path:
    return trainer_root() / "recipes"


def list_recipes() -> list[str]:
    return sorted(path.name for path in recipes_dir().glob("*.yaml") if path.is_file())


def recipe_path(recipe: str) -> Path:
    if Path(recipe).name != recipe or not recipe.endswith(".yaml"):
        raise DatasetError("recipe does not exist")
    
    path: Path = recipes_dir() / recipe
    
    if not path.is_file():
        raise DatasetError("recipe does not exist")
    
    return path


def load_recipe(recipe: str) -> dict[str, Any]:
    try:
        loaded: object = yaml.safe_load(recipe_path(recipe).read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise DatasetError("recipe is invalid") from exc

    if not isinstance(loaded, dict):
        raise DatasetError("recipe backend is invalid")

    try:
        Backend(loaded.get("backend"))
    except ValueError:
        raise DatasetError("recipe backend is invalid") from None

    return loaded


def get_recipe_backend(recipe: str) -> Backend:
    return Backend(load_recipe(recipe)["backend"])
