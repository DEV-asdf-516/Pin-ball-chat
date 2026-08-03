import json
import shutil
import sqlite3
import time
from pathlib import Path

from core.db import immediate_transaction, new_id
from core.errors import BadRequest, Conflict
from domain.conversations.importer.session_store import (
    SESSION_TTL_SECONDS,
    StoredImportSession,
    ensure_sessions_root,
    find_session,
    get_import_session,
    is_expired,
    lock_for,
    public_session,
    read_json_file,
    session_dir,
    session_meta_path,
    write_json_file,
)
from domain.conversations.importer.validation import (
    MAX_BYTES,
    MAX_MESSAGES,
    ImportedMessage,
    ImportSession,
    part_info,
    validate_manifest,
    validate_part,
)
from domain.conversations.reader import ensure_conversation_empty, has_import_action
from domain.conversations.writer import record_zeta_import
from util.time_util import utc_now_string


def _require_importable(conn: sqlite3.Connection, conversation_id: str, current_session_id: str | None = None) -> dict:
    conversation: dict = ensure_conversation_empty(conn, conversation_id)
    directory: Path = session_dir(conversation_id)
    meta_path: Path = session_meta_path(directory)

    if meta_path.exists():
        stored: StoredImportSession = StoredImportSession.from_dict(read_json_file(meta_path))

        if stored.session_id != current_session_id:
            raise Conflict("conversation already has an active import session")

    return conversation


def _cleanup_stale_session(conn: sqlite3.Connection, conversation_id: str) -> None:
    directory: Path = session_dir(conversation_id)

    if not directory.exists():
        return

    meta_path: Path = session_meta_path(directory)

    if not meta_path.exists():
        if time.time() - directory.stat().st_mtime >= SESSION_TTL_SECONDS:
            shutil.rmtree(directory)
        return

    stored: StoredImportSession = StoredImportSession.from_dict(read_json_file(meta_path))

    if not is_expired(stored):
        return

    if stored.state == "uploading" or has_import_action(conn, conversation_id):
        shutil.rmtree(directory)
        return

    try:
        _require_importable(conn, conversation_id, stored.session_id)
    except Conflict:
        return

    shutil.rmtree(directory)


def start_import_session(conn: sqlite3.Connection, conversation_id: str, meta: dict) -> dict:
    session: ImportSession = ImportSession.from_dict(meta)

    with lock_for(conversation_id):
        ensure_sessions_root()
        _cleanup_stale_session(conn, conversation_id)
        _require_importable(conn, conversation_id)

        directory: Path = session_dir(conversation_id)
        meta_path: Path = session_meta_path(directory)

        try:
            directory.mkdir()
        except FileExistsError as exc:
            raise Conflict("conversation already has an active import session") from exc

        now: str = utc_now_string()
        session_id: str = new_id("zimp_session")

        stored: StoredImportSession = StoredImportSession(
            session_id=session_id,
            conversation_id=conversation_id,
            room_id=session.room_id,
            expected_parts=session.expected_parts,
            expected_messages=session.expected_messages,
            received_messages=0,
            received_bytes=0,
            warning_count=0,
            parts={},
            manifest=session.manifest,
            created_at=now,
            last_activity_at=now,
            state="uploading",
        )
        
        try:
            write_json_file(meta_path, stored.to_dict())
        except BaseException:
            shutil.rmtree(directory, ignore_errors=True)
            raise

        return public_session(stored)


def upload_import_part(session_id: str, part_number: int, part: dict) -> dict:
    conversation_id, directory, _ = find_session(session_id)
    meta_path: Path = session_meta_path(directory)

    with lock_for(conversation_id):
        stored: StoredImportSession = StoredImportSession.from_dict(read_json_file(meta_path))

        stored.ensure_session_id(session_id)

        if is_expired(stored):
            if stored.state == "uploading":
                shutil.rmtree(directory)

            raise Conflict("import session expired; start again")

        stored.ensure_uploading()
        stored.ensure_part_number(part_number)

        _, warnings = validate_part(part, stored.room_id)

        payload: bytes = json.dumps(part, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

        next_stored: StoredImportSession = stored.record_part(part_number, part_info(part, len(payload), len(warnings)))

        if next_stored.received_messages > MAX_MESSAGES:
            raise BadRequest(f"import exceeds the {MAX_MESSAGES} message limit")

        if next_stored.received_bytes > MAX_BYTES:
            raise BadRequest(f"import exceeds the {MAX_BYTES} byte limit")

        write_json_file(directory / f"part-{part_number:06d}.json", part)

        stored = next_stored
        write_json_file(meta_path, stored.to_dict())

        result: dict = public_session(stored)
        result["partNumber"] = part_number
        result["warnings"] = warnings

        return result


def commit_import_session(conn: sqlite3.Connection, session_id: str) -> dict:
    conversation_id, directory, _ = find_session(session_id)
    meta_path: Path = session_meta_path(directory)

    with lock_for(conversation_id):
        stored: StoredImportSession = StoredImportSession.from_dict(read_json_file(meta_path))

        stored.ensure_session_id(session_id)

        if is_expired(stored):
            _cleanup_stale_session(conn, conversation_id)
            raise Conflict("import session expired; start again")

        stored.ensure_uploading()

        stored = stored.mark_committing()

        write_json_file(meta_path, stored.to_dict())

        try:
            stored.ensure_all_parts_received()
            stored.ensure_message_count_matches()

            validate_manifest(stored)

            messages: list[ImportedMessage] = []
            warnings: list[str] = []

            for part_number in range(1, stored.expected_parts + 1):
                part: dict = read_json_file(directory / f"part-{part_number:06d}.json")
                validated, part_warnings = validate_part(part, stored.room_id)
                messages.extend(validated)
                warnings.extend(part_warnings)

            messages_by_id: dict[str, ImportedMessage] = {}

            for message in messages:
                existing_message: ImportedMessage | None = messages_by_id.get(message.id)

                if existing_message is not None and existing_message.canonical_json != message.canonical_json:
                    raise BadRequest(f"duplicate message id has conflicting payload: {message.id}")

                messages_by_id.setdefault(message.id, message)

            ordered_messages: list[ImportedMessage] = sorted(
                messages_by_id.values(),
                key=lambda message: (message.sort_key, message.id),
            )

            if not ordered_messages:
                raise BadRequest("import contains no valid messages")

            messages = ordered_messages
        except BaseException:
            stored = stored.mark_uploading()
            write_json_file(meta_path, stored.to_dict())
            raise
        
        with immediate_transaction(conn):
            conversation: dict = _require_importable(conn, conversation_id, session_id)
            result: dict = record_zeta_import(conn, stored, conversation, messages, warnings)
        shutil.rmtree(directory)
        
        return result


def discard_import_session(session_id: str) -> dict:
    conversation_id, directory, _ = find_session(session_id)
    meta_path: Path = session_meta_path(directory)
    with lock_for(conversation_id):
        stored: StoredImportSession = StoredImportSession.from_dict(read_json_file(meta_path))
        stored.ensure_session_id(session_id)
        stored.ensure_uploading()
        shutil.rmtree(directory)
        return {"sessionId": session_id, "discarded": True}
