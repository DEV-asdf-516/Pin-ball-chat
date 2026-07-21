# Import a JSONL file into a trainer dataset folder.

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any


ROOT: Path = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trainer.domain.datasets import DatasetError, DatasetFormat, validate_format
from trainer.domain.importer import create_dataset_from_upload

log = logging.getLogger(__name__)


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    parser: argparse.ArgumentParser = argparse.ArgumentParser()
    parser.add_argument("file", type=Path)
    parser.add_argument("--name", required=True)
    parser.add_argument("--format", required=True, choices=[f.value for f in DatasetFormat])
    args: argparse.Namespace = parser.parse_args()
    
    try:
        dataset_format: DatasetFormat = validate_format(args.format)
        raw: bytes = args.file.read_bytes()
        result: dict[str, Any] = create_dataset_from_upload(args.name, dataset_format, raw, args.file.name)
    except (DatasetError, FileExistsError, OSError) as exc:
        log.error("%s", exc)
        return 1

    print(f"dataset={result['dataset']} row_count={result['row_count']} "
          f"rejected_rows={result['rejected_rows']} duplicates_removed={result['duplicates_removed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
