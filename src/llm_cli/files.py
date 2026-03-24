import base64
import mimetypes
from pathlib import Path

from .utils import fail, resolve_path


def detect_mime_type(file_path, expected_kind=None):
    mime_type, _ = mimetypes.guess_type(str(file_path))
    if expected_kind == "image":
        if mime_type and mime_type.startswith("image/"):
            return mime_type
        return None
    if expected_kind == "audio":
        if mime_type and mime_type.startswith("audio/"):
            return mime_type
        ext_map = {
            ".m4a": "audio/mp4",
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".ogg": "audio/ogg",
            ".flac": "audio/flac",
            ".aac": "audio/aac",
            ".wma": "audio/x-ms-wma",
            ".webm": "audio/webm",
        }
        return ext_map.get(Path(file_path).suffix.lower())
    return mime_type or "application/octet-stream"


def is_image_attachment(file_path):
    return bool(detect_mime_type(file_path, expected_kind="image"))


def is_audio_attachment(file_path):
    return bool(detect_mime_type(file_path, expected_kind="audio"))


def is_text_attachment(file_path):
    path = resolve_path(file_path)
    mime_type = detect_mime_type(path)
    if mime_type.startswith("text/"):
        return True
    return Path(path).suffix.lower() in {
        ".md",
        ".markdown",
        ".txt",
        ".json",
        ".jsonl",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".conf",
        ".csv",
        ".tsv",
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".java",
        ".c",
        ".cc",
        ".cpp",
        ".h",
        ".hpp",
        ".go",
        ".rs",
        ".sh",
        ".bash",
        ".zsh",
        ".log",
        ".srt",
        ".lrc",
        ".xml",
        ".html",
        ".css",
        ".sql",
    }


def read_text_attachment(file_path):
    path = resolve_path(file_path)
    if not path.exists():
        fail(f"附件不存在: {path}")
    if not path.is_file():
        fail(f"附件不是文件: {path}")
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        fail(f"文本附件不是有效的 UTF-8 文本: {path}")
    except OSError as exc:
        fail(f"读取文本附件失败: {path} ({exc})")
    return {
        "path": str(path),
        "content": content.rstrip(),
        "language": path.suffix.lower().lstrip(".") or "text",
    }


def load_binary_attachment(file_path, expected_kind=None):
    path = resolve_path(file_path)
    if not path.exists():
        fail(f"附件不存在: {path}")
    if not path.is_file():
        fail(f"附件不是文件: {path}")

    mime_type = detect_mime_type(path, expected_kind=expected_kind)
    if not mime_type:
        fail(f"无法识别文件类型: {path}，请确认这是有效的 {expected_kind} 文件")
    if expected_kind and not mime_type.startswith(f"{expected_kind}/"):
        fail(f"文件类型不匹配: {path} -> {mime_type}，预期 {expected_kind}/*")

    try:
        data = base64.b64encode(path.read_bytes()).decode("utf-8")
    except OSError as exc:
        fail(f"读取附件失败: {path} ({exc})")
    return {
        "path": str(path),
        "mime_type": mime_type,
        "base64_data": data,
    }
