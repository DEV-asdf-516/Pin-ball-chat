import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from core.errors import BadRequest
from domain.conversations.importer.session_store import PartInfo, StoredImportSession
from util.safe_util import get_or_default
from util.string_util import camel_to_snake
from util.validation_util import required_bounded_int, required_nonblank_text

MAX_PARTS = 64
MAX_MESSAGES = 50_000
MAX_BYTES = 256 * 1024 * 1024

_speaker_prefix = re.compile(r"^@[^:\n]{0,40}:", re.MULTILINE)
_iso_time = re.compile(
    r"^(?P<base>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(?P<fraction>\d{1,9}))?(?P<zone>Z|[+-]\d{2}:\d{2})$"
)

_INVALID_MESSAGE_TIME = "messageTime must be a valid ISO 8601 timestamp"


def _parse_message_time(value: object) -> tuple[int, str]:
    if not isinstance(value, str):
        raise BadRequest(_INVALID_MESSAGE_TIME)

    time_match: re.Match[str] | None = _iso_time.fullmatch(value)

    if not time_match:
        raise BadRequest(_INVALID_MESSAGE_TIME)

    fraction: str = (time_match.group("fraction") or "").ljust(9, "0")

    try:
        parsed: datetime = datetime.fromisoformat(
            time_match.group("base") + (f".{fraction[:6]}" if fraction else "") + time_match.group("zone")
        )
    except ValueError as exc:
        raise BadRequest(_INVALID_MESSAGE_TIME) from exc
    
    utc_time: datetime = parsed.astimezone(timezone.utc)
    seconds: int = int(utc_time.timestamp())
    nanoseconds: int = int(fraction or "0")
    
    return seconds * 1_000_000_000 + nanoseconds, utc_time.strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True, slots=True)
class ImportSession:
    room_id: str
    expected_parts: int
    expected_messages: int
    manifest: dict | None

    @classmethod
    def from_dict(cls, meta: dict) -> "ImportSession":
        if not isinstance(meta, dict):
            raise BadRequest("request body must be an object")

        room_id: str = required_nonblank_text(meta.get("roomId"), "roomId")
        
        expected_parts: int = required_bounded_int(
            meta.get("expectedParts"), 
            "expectedParts", minimum=1, 
            maximum=MAX_PARTS
        )
        
        expected_messages: int = required_bounded_int(
            meta.get("expectedMessages"), 
            "expectedMessages", 
            minimum=0, 
            maximum=MAX_MESSAGES
        )
        
        manifest: object = meta.get("manifest")
        
        if manifest is not None and not isinstance(manifest, dict):
            raise BadRequest("manifest must be an object")
        
        if manifest and manifest.get("roomId") is not None and manifest.get("roomId") != room_id:
            raise BadRequest("manifest roomId does not match roomId")
        
        return cls(room_id=room_id, expected_parts=expected_parts, expected_messages=expected_messages, manifest=manifest)


@dataclass(frozen=True, slots=True)
class ImportedMessage:
    id: str
    room_id: str
    role: str
    content: str
    sort_key: int
    created_at: str
    canonical_json: str


def validate_part(part: dict, room_id: str) -> tuple[list[ImportedMessage], list[str]]:
    def _required_text(value: object, field: str) -> str:
        if not isinstance(value, str):
            raise BadRequest(f"{field} must be a string")
        return value

    if not isinstance(part, dict) or not isinstance(part.get("messages"), list):
        raise BadRequest("messages must be an array")

    validated: list[ImportedMessage] = []
    warnings: list[str] = []

    for raw in part["messages"]:
        if not isinstance(raw, dict):
            raise BadRequest("each message must be an object")

        message_id: str = required_nonblank_text(raw.get("id"), "message id")
        warning_prefix: str = f"[메시지 {message_id}] "
        message_room_id: str = required_nonblank_text(raw.get("roomId"), "message roomId")
        
        if message_room_id != room_id:
            raise BadRequest("part contains a message from a different room")

        sender: object = raw.get("sender")
        sender_type: object = sender.get("type") if isinstance(sender, dict) else None
        
        if sender_type not in ("USER", "BOT"):
            raise BadRequest("sender.type must be USER or BOT")

        sort_key, created_at = _parse_message_time(raw.get("messageTime"))
        contents: object = raw.get("contents")
        
        if not isinstance(contents, list):
            warnings.append(f"{warning_prefix}내용 형식이 올바르지 않아 이 메시지를 건너뛰었습니다.")
            continue

        texts: list[str] = []

        for block_index, block in enumerate(contents):
            if not isinstance(block, dict) or block.get("type") != "TEXT":
                warnings.append(f"{warning_prefix}{block_index + 1}번째 항목은 텍스트가 아니라서 건너뛰었습니다.")
                continue

            text: str = _required_text(block.get("text"), "text")
            speaker_name: str = _required_text(block.get("speakerName"), "speakerName")

            if _speaker_prefix.search(text):
                warnings.append(f"{warning_prefix}내용 중에 '@speaker:' 형식의 문구가 있어 화자 표시와 헷갈릴 수 있습니다.")

            is_narrator: bool = block.get("position") == "NARRATOR" or speaker_name.strip() in ("내레이터", "나레이터")

            if is_narrator:
                formatted_text: str = f"@관찰자: {text}"
            else:
                normalized: str = speaker_name.replace(":", "").replace("\n", "").replace("\r", "").strip()[:40]
                
                if not normalized:
                    warnings.append(f"{warning_prefix}화자 이름이 비어 있어 '관찰자'로 대신 표시했습니다.")
                
                formatted_text = f"@{normalized or '관찰자'}: {text}"

            if text.strip():
                texts.append(formatted_text)

        if not texts:
            warnings.append(f"{warning_prefix}표시할 내용이 없어 이 메시지를 건너뛰었습니다.")
            continue

        canonical: str = json.dumps(
            {
                "messageTime": raw.get("messageTime"), 
                "sender": sender, 
                "contents": contents
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

        validated.append(ImportedMessage(
            id=message_id,
            room_id=message_room_id,
            role="user" if sender_type == "USER" else "assistant",
            content="\n\n".join(texts),
            sort_key=sort_key,
            created_at=created_at,
            canonical_json=canonical,
        ))

    return validated, warnings


def part_info(part: dict, byte_count: int, warning_count: int) -> PartInfo:
    messages: list = part["messages"]
    return PartInfo(
        message_count=len(messages),
        byte_count=byte_count,
        warning_count=warning_count,
        first_message_id=messages[0].get("id") if messages and isinstance(messages[0], dict) else None,
        last_message_id=messages[-1].get("id") if messages and isinstance(messages[-1], dict) else None,
    )


def validate_manifest(session: StoredImportSession) -> None:
    def _manifest_part_number(item: dict, fallback: int) -> int:
        for key in ("partNumber", "partNo", "part"):
            part_number: object = item.get(key)

            if not isinstance(part_number, bool) and isinstance(part_number, int):
                return part_number

        filename: object = item.get("fileName") or item.get("filename") or item.get("name")
        filename_match: re.Match[str] | None = re.search(r"part-(\d+)", filename) if isinstance(filename, str) else None

        return int(filename_match.group(1)) if filename_match else fallback

    manifest: dict | None = session.manifest

    if not manifest:
        return

    total: object = get_or_default(manifest, "totalMessages", fallback_key="messageCount")

    if total is not None and total != session.received_messages:
        raise BadRequest("manifest total message count does not match uploaded parts")

    listed_parts: object = manifest.get("parts")

    if not isinstance(listed_parts, list):
        return

    for index, expected in enumerate(listed_parts, 1):
        if not isinstance(expected, dict):
            raise BadRequest("manifest parts must be objects")

        actual: PartInfo | None = session.parts.get(str(_manifest_part_number(expected, index)))

        if actual is None:
            raise BadRequest("manifest references a missing part")

        for check_key in ("messageCount", "firstMessageId", "lastMessageId"):
            if check_key not in expected:
                continue
            
            actual_value: object = getattr(actual, camel_to_snake(check_key))
            
            if expected[check_key] != actual_value:
                raise BadRequest(f"manifest {check_key} does not match uploaded part")
