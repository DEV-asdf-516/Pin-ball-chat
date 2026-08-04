import sqlite3
from pathlib import Path

from core.db import DATA_ROOT, Bind, OrderBy, ReadQuery, transaction_with_rollback, find_all
from core.errors import get_or_raise
from domain.catalog.reader import find_catalog_by_id
from domain.catalog.specs import CatalogKind, SPEC_BY_KIND
from domain.catalog.writer import catalog_file_path, catalog_file_paths, create_catalog_item, delete_catalog_item, update_catalog_item
from domain.characters import MAX_PLOT_CHARACTERS, create_character
from domain.conversations.specs import CONVERSATIONS
from domain.conversations.writer import delete_conversation

def get_plot(conn: sqlite3.Connection, plot_id: str) -> dict:
    row: dict | None = find_catalog_by_id(conn, CatalogKind.PLOT, plot_id)
    return get_or_raise(row, f"plot {plot_id} not found")


def list_plot_characters(conn: sqlite3.Connection, plot_id: str) -> list[dict]:
    return find_all(
        conn,
        ReadQuery(
            SPEC_BY_KIND[CatalogKind.CHARACTER],
            where=Bind({"plot_id": plot_id}),
            order_by=(OrderBy("sort_order"), OrderBy("id")),
        ),
    )


def create_plot(conn: sqlite3.Connection, data: dict, root: Path = DATA_ROOT) -> dict:
    characters: object = data.get("characters")

    if not isinstance(characters, list) or not characters:
        raise ValueError("characters must contain at least one character")

    if len(characters) > MAX_PLOT_CHARACTERS:
        raise ValueError("a plot can have at most 10 characters")

    plot_id: str = data.get("id", "")
    plot_data: dict = {
        "type": "plot",
        **{key: value for key, value in data.items() if key != "characters"},
    }
    created_paths: list[Path] = []

    def rollback_created_paths() -> None:
        for path in reversed(created_paths):
            path.unlink(missing_ok=True)

    with transaction_with_rollback(conn, rollback_created_paths):
        create_catalog_item(conn, CatalogKind.PLOT, plot_data, root=root)
        created_paths.append(catalog_file_path(CatalogKind.PLOT, plot_id, root))

        for sort_order, raw_character in enumerate(characters):
            if not isinstance(raw_character, dict):
                raise ValueError("each character must be an object")

            character_data: dict = {
                **raw_character,
                "plotId": plot_id,
                "sortOrder": sort_order,
            }
            character: dict = create_character(conn, character_data, root=root)
            created_paths.append(catalog_file_path(CatalogKind.CHARACTER, character["id"], root))

    return get_plot(conn, plot_id)


def update_plot(conn: sqlite3.Connection, plot_id: str, data: dict, root: Path = DATA_ROOT) -> dict:
    # 캐릭터 추가·삭제·정렬은 개별 character CRUD로 처리하므로, plot update에 실린 배열은 저장하지 않는다.
    plot_data: dict = {key: value for key, value in data.items() if key != "characters"}
    return update_catalog_item(conn, CatalogKind.PLOT, plot_id, plot_data, root=root)


def delete_plot(conn: sqlite3.Connection, plot_id: str, root: Path = DATA_ROOT) -> dict:
    get_plot(conn, plot_id)
    characters: list[dict] = list_plot_characters(conn, plot_id)

    snapshots: dict[Path, bytes] = {
        path: path.read_bytes()
        for path in list(catalog_file_paths(CatalogKind.PLOT, plot_id, root))
        + [path for character in characters for path in catalog_file_paths(CatalogKind.CHARACTER, character["id"], root)]
        if path.exists()
    }

    def rollback_snapshots() -> None:
        for path, content in snapshots.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

    with transaction_with_rollback(conn, rollback_snapshots):
        conversations: list[dict] = find_all(
            conn,
            ReadQuery(CONVERSATIONS, where=Bind({"plot_id": plot_id})),
        )

        for conversation in conversations:
            delete_conversation(conn, conversation["id"])

        for character in characters:
            delete_catalog_item(conn, CatalogKind.CHARACTER, character["id"], root=root)

        result: dict = delete_catalog_item(conn, CatalogKind.PLOT, plot_id, root=root)

    return result
