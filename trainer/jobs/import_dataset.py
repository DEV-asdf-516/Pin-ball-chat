"""Import a JSONL file into a trainer dataset folder."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trainer.api.dataset_io import DatasetError, create_dataset, datasets_dir, validate_format, validate_name, write_rows
from trainer.api.importer import import_file


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("file", type=Path)
    parser.add_argument("--name", required=True)
    parser.add_argument("--format", required=True, choices=("chat", "preference"))
    args = parser.parse_args()
    try:
        name = validate_name(args.name)
        dataset_format = validate_format(args.format)
        if (datasets_dir() / name).exists():
            raise DatasetError("dataset already exists")
        result = import_file(args.file, dataset_format)
        if not result.rows:
            raise DatasetError("no valid rows")
        create_dataset(name, dataset_format, "import", args.file.name)
        row_count = write_rows(name, dataset_format, result.rows)
    except (DatasetError, FileExistsError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"dataset={name} row_count={row_count} rejected_rows={result.rejected_rows} duplicates_removed={result.duplicates_removed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
