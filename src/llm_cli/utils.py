import sys
from pathlib import Path

MODE_ALIASES = {"chat", "text", "image", "tts", "video"}
IMAGE_SIZE_CHOICES = ("512", "1K", "2K", "4K")
IMAGE_ASPECT_CHOICES = ("1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "4:5", "5:4", "21:9")
VIDEO_SECONDS_CHOICES = ("4", "8", "10", "12", "15", "16", "20")
VIDEO_SIZE_CHOICES = ("720x1280", "1280x720", "1024x1024", "720p")


def fail(message):
    print(f"错误: {message}", file=sys.stderr)
    sys.exit(1)


def resolve_path(path_value, base_dir=None):
    path = Path(path_value).expanduser()
    if base_dir and not path.is_absolute():
        path = Path(base_dir) / path
    return path.resolve()


def resolve_text(value, base_dir=None):
    if value is None:
        return None
    if not isinstance(value, str):
        return str(value)
    if not value.startswith("@"):
        return value

    file_path = resolve_path(value[1:], base_dir=base_dir)
    if not file_path.exists():
        fail(f"文件不存在: {file_path}")
    if not file_path.is_file():
        fail(f"路径不是文件: {file_path}")
    try:
        return file_path.read_text(encoding="utf-8").strip()
    except UnicodeDecodeError:
        fail(f"文件不是有效的 UTF-8 文本: {file_path}")
    except OSError as exc:
        fail(f"读取文件失败: {file_path} ({exc})")


def read_text_file(path_value, base_dir=None, missing_label="文件"):
    file_path = resolve_path(path_value, base_dir=base_dir)
    if not file_path.exists():
        fail(f"{missing_label}不存在: {file_path}")
    if not file_path.is_file():
        fail(f"路径不是文件: {file_path}")
    try:
        return file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        fail(f"文件不是有效的 UTF-8 文本: {file_path}")
    except OSError as exc:
        fail(f"读取文件失败: {file_path} ({exc})")


def read_input_files(paths, base_dir=None):
    chunks = []
    for raw_path in paths or []:
        content = read_text_file(raw_path, base_dir=base_dir, missing_label="输入文件")
        file_path = resolve_path(raw_path, base_dir=base_dir)
        chunks.append(f"## 文件: {file_path.name}\n\n{content.strip()}")
    return "\n\n".join(chunk for chunk in chunks if chunk.strip())


def join_message_parts(*parts):
    normalized = [str(part).strip() for part in parts if part and str(part).strip()]
    return "\n\n".join(normalized)
