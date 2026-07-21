# Export application rows through the same dataset writer used by the API.

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any


ROOT: Path = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trainer.core.db.app_db import app_db_connection, export_application_rows
from trainer.core.errors import AppDbUnavailable
from trainer.domain.datasets import CreateDatasetParams, DatasetError, DatasetFormat, create_dataset_from_candidates, validate_format, validate_name

log = logging.getLogger(__name__)


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    
    parser: argparse.ArgumentParser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--format", required=True, choices=[f.value for f in DatasetFormat])
    parser.add_argument("--generated-by", required=True)
    
    args: argparse.Namespace = parser.parse_args()
    
    try:
        name: str = validate_name(args.name)
        dataset_format: DatasetFormat = validate_format(args.format)

        if not args.generated_by.strip():
            raise DatasetError("generated_by is required for app_export")

        with app_db_connection() as conn:
            exported: list[dict[str, Any]] = export_application_rows(conn, dataset_format)

        params: CreateDatasetParams = CreateDatasetParams(
            name,
            dataset_format,
            source="app_export",
            origin=f"APP_DB_PATH export format={dataset_format}",
            generated_by=args.generated_by,
        )
        result: dict[str, Any] = create_dataset_from_candidates(params, exported)

    except (AppDbUnavailable, DatasetError, FileExistsError, OSError) as exc:
        log.error("%s", exc)
        return 1

    print(json.dumps(result, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
