import json
import os
import shutil
import tempfile
import threading
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from core.db import DATA_ROOT
from core.errors import BadRequest, Conflict, NotFound
from util.time_util import utc_now_string
from util.validation_util import required_bounded_int

SESSION_TTL_SECONDS = 60 * 60
IMPORT_SESSIONS_ROOT = DATA_ROOT / "tmp" / "import_sessions"

_locks_guard = threading.Lock()
_locks: dict[str, threading.Lock] = {}


def lock_for(conversation_id: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(conversation_id, threading.Lock())


def session_dir(conversation_id: str) -> Path:
    return IMPORT_SESSIONS_ROOT / conversation_id


def ensure_sessions_root() -> None:
    IMPORT_SESSIONS_ROOT.mkdir(parents=True, exist_ok=True)


def session_meta_path(directory: Path) -> Path:
    return directory / "session.json"


def write_json_file(path: Path, value: dict) -> int:
    serialized: str = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    payload: bytes = serialized.encode("utf-8")
    file_descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    
    try:
        with os.fdopen(file_descriptor, "wb") as output_file:
            output_file.write(payload)
            output_file.flush()
            os.fsync(output_file.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise
    
    return len(payload)


def read_json_file(path: Path) -> dict:
    try:
        text: str = path.read_text(encoding="utf-8")
        value: object = json.loads(text)
    except (OSError, json.JSONDecodeError) as exc:
        raise Conflict("import session metadata is damaged") from exc

    if not isinstance(value, dict):
        raise Conflict("import session metadata is damaged")

    return value


@dataclass(frozen=True, slots=True)
class PartInfo:
    message_count: int
    byte_count: int
    warning_count: int
    first_message_id: str | None
    last_message_id: str | None

    @classmethod
    def from_dict(cls, data: dict) -> "PartInfo":
        return cls(
            message_count=data["messageCount"],
            byte_count=data["byteCount"],
            warning_count=data["warningCount"],
            first_message_id=data.get("firstMessageId"),
            last_message_id=data.get("lastMessageId"),
        )

    @classmethod
    def empty(cls) -> "PartInfo":
        return cls(message_count=0, byte_count=0, warning_count=0, first_message_id=None, last_message_id=None)

    def to_dict(self) -> dict:
        return {
            "messageCount": self.message_count,
            "byteCount": self.byte_count,
            "warningCount": self.warning_count,
            "firstMessageId": self.first_message_id,
            "lastMessageId": self.last_message_id,
        }


@dataclass(frozen=True, slots=True)
class StoredImportSession:
    session_id: str
    conversation_id: str
    room_id: str
    expected_parts: int
    expected_messages: int
    received_messages: int
    received_bytes: int
    warning_count: int
    parts: dict[str, PartInfo]
    manifest: dict | None
    created_at: str
    last_activity_at: str
    state: str

    @classmethod
    def from_dict(cls, meta: dict) -> "StoredImportSession":
        try:
            return cls(
                session_id=meta["sessionId"],
                conversation_id=meta["conversationId"],
                room_id=meta["roomId"],
                expected_parts=meta["expectedParts"],
                expected_messages=meta["expectedMessages"],
                received_messages=meta.get("receivedMessages", 0),
                received_bytes=meta.get("receivedBytes", 0),
                warning_count=meta.get("warningCount", 0),
                parts={key: PartInfo.from_dict(value) for key, value in meta.get("parts", {}).items()},
                manifest=meta.get("manifest"),
                created_at=meta["createdAt"],
                last_activity_at=meta["lastActivityAt"],
                state=meta["state"],
            )
        except KeyError as exc:
            raise Conflict("import session metadata is damaged") from exc

    def to_dict(self) -> dict:
        return {
            "sessionId": self.session_id,
            "conversationId": self.conversation_id,
            "roomId": self.room_id,
            "expectedParts": self.expected_parts,
            "expectedMessages": self.expected_messages,
            "receivedMessages": self.received_messages,
            "receivedBytes": self.received_bytes,
            "warningCount": self.warning_count,
            "parts": {key: value.to_dict() for key, value in self.parts.items()},
            "manifest": self.manifest,
            "createdAt": self.created_at,
            "lastActivityAt": self.last_activity_at,
            "state": self.state,
        }

    def record_part(self, part_number: int, info: PartInfo) -> "StoredImportSession":
        previous: PartInfo = self.parts.get(str(part_number), PartInfo.empty())

        return replace(
            self,
            parts={**self.parts, str(part_number): info},
            received_messages=self.received_messages - previous.message_count + info.message_count,
            received_bytes=self.received_bytes - previous.byte_count + info.byte_count,
            warning_count=self.warning_count - previous.warning_count + info.warning_count,
            last_activity_at=utc_now_string(),
        )

    def mark_committing(self) -> "StoredImportSession":
        return replace(self, state="committing", last_activity_at=utc_now_string())

    def mark_uploading(self) -> "StoredImportSession":
        return replace(self, state="uploading", last_activity_at=utc_now_string())

    def ensure_part_number(self, part_number: int) -> None:
        # 계획에 없는 part_number로 고아 파일이 생기지 않도록, 이 세션이 선언한 범위 안인지 스스로 확인한다.
        required_bounded_int(part_number, "part number", minimum=1, maximum=self.expected_parts)

    def ensure_session_id(self, session_id: str) -> None:
        if self.session_id != session_id:
            raise NotFound("import session not found")

    def ensure_uploading(self) -> None:
        if self.state != "uploading":
            raise Conflict("import session is committing")

    def ensure_all_parts_received(self) -> None:
        expected_numbers: set[int] = set(range(1, self.expected_parts + 1))
        received_numbers: set[int] = {int(number) for number in self.parts}
        missing: list[int] = sorted(expected_numbers - received_numbers)

        if missing:
            raise BadRequest(f"missing import part(s): {', '.join(map(str, missing))}")

    def ensure_message_count_matches(self) -> None:
        if self.received_messages != self.expected_messages:
            raise BadRequest("uploaded message count does not match expectedMessages")


def public_session(session: StoredImportSession) -> dict:
    received_parts: list[int] = sorted(int(number) for number in session.parts)
    return {
        "sessionId": session.session_id,
        "conversationId": session.conversation_id,
        "roomId": session.room_id,
        "expectedParts": session.expected_parts,
        "expectedMessages": session.expected_messages,
        "receivedParts": received_parts,
        "receivedMessages": session.received_messages,
        "receivedBytes": session.received_bytes,
        "warningCount": session.warning_count,
        "state": session.state,
        "createdAt": session.created_at,
        "lastActivityAt": session.last_activity_at,
    }


def is_expired(session: StoredImportSession) -> bool:
    try:
        last_activity: datetime = datetime.fromisoformat(session.last_activity_at)
    except (TypeError, ValueError):
        return True
    return (datetime.now(timezone.utc) - last_activity).total_seconds() >= SESSION_TTL_SECONDS


def find_session(session_id: str) -> tuple[str, Path, dict]:
    if not isinstance(session_id, str) or not session_id:
        raise NotFound("import session not found")

    if not IMPORT_SESSIONS_ROOT.exists():
        raise NotFound("import session not found")

    for directory in IMPORT_SESSIONS_ROOT.iterdir():
        if not directory.is_dir():
            continue

        meta_path: Path = session_meta_path(directory)

        if not meta_path.exists():
            continue

        stored_meta: dict = read_json_file(meta_path)

        if stored_meta.get("sessionId") == session_id:
            conversation_id: str = str(stored_meta.get("conversationId", directory.name))
            return conversation_id, directory, stored_meta

    raise NotFound("import session not found")


def get_import_session(conversation_id: str) -> dict | None:
    with lock_for(conversation_id):
        directory: Path = session_dir(conversation_id)
        meta_path: Path = session_meta_path(directory)

        if not meta_path.exists():
            return None

        session: StoredImportSession = StoredImportSession.from_dict(read_json_file(meta_path))

        if is_expired(session) and session.state == "uploading":
            shutil.rmtree(meta_path.parent)
            return None

        return public_session(session)
