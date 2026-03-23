import json
from datetime import datetime, timezone
from pathlib import Path


def _now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def resolve_session_path(session_value=None, *, cwd=None, interactive=False):
    base_dir = Path(cwd or Path.cwd()).resolve()
    if not session_value:
        return None

    session_path = Path(session_value).expanduser()
    has_path_hint = session_path.is_absolute() or any(part in {".", ".."} for part in session_path.parts) or session_path.parent != Path(".")
    if not has_path_hint and session_path.suffix == "":
        session_path = Path(f"{session_value}.jsonl")
    if not session_path.is_absolute():
        session_path = base_dir / session_path
    return session_path.resolve()


def _normalize_content(content):
    if content is None:
        return ""
    return content


def load_session_messages(session_path):
    path = Path(session_path)
    if not path.exists():
        return []

    messages = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("type") != "message":
            continue
        role = record.get("role")
        if role not in {"system", "user", "assistant"}:
            continue
        message = {"role": role, "content": _normalize_content(record.get("content"))}
        meta = record.get("meta")
        if isinstance(meta, dict) and meta:
            message["meta"] = meta
        messages.append(message)
    return messages


def append_session_messages(session_path, messages):
    path = Path(session_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for message in messages:
            record = {
                "type": "message",
                "role": message["role"],
                "content": _normalize_content(message.get("content")),
                "created_at": _now_iso(),
            }
            meta = message.get("meta")
            if isinstance(meta, dict) and meta:
                record["meta"] = meta
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def rewrite_session_messages(session_path, messages):
    path = Path(session_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    if messages:
        append_session_messages(path, messages)


def clear_session_file(session_path):
    rewrite_session_messages(session_path, [])


def replace_leading_system_messages(messages, system_prompt):
    remaining = list(messages or [])
    while remaining and remaining[0].get("role") == "system":
        remaining.pop(0)
    if system_prompt:
        return [{"role": "system", "content": system_prompt}, *remaining]
    return remaining
