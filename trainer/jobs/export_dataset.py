"""Export application rows through the same dataset writer used by the API."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trainer.api.dataset_io import app_db_connection, DatasetError, canonical_hash, create_dataset, datasets_dir, export_application_rows, validate_format, validate_name, validate_row, write_rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--format", required=True, choices=("chat", "preference"))
    parser.add_argument("--generated-by", required=True)
    args = parser.parse_args()
    try:
        name = validate_name(args.name)
        dataset_format = validate_format(args.format)
        if not args.generated_by.strip():
            raise DatasetError("generated_by is required for app_export")
        if (datasets_dir() / name).exists():
            raise DatasetError("dataset already exists")
        with app_db_connection() as connection:
            exported = export_application_rows(connection, dataset_format)
        rows = []
        seen = set()
        for row in exported:
            try:
                checked = validate_row(row, dataset_format)
            except DatasetError:
                continue
            key = canonical_hash(checked)
            if key not in seen:
                seen.add(key)
                rows.append(checked)
        create_dataset(name, dataset_format, "app_export", f"APP_DB_PATH export format={dataset_format}", args.generated_by)
        row_count = write_rows(name, dataset_format, rows)
    except (DatasetError, FileExistsError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"dataset": name, "row_count": row_count}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
