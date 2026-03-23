import base64
import json
import re
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from .utils import fail


def extract_text_result(response):
    message = response.choices[0].message
    content = getattr(message, "content", None)

    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(item.get("text", ""))
                else:
                    parts.append(json.dumps(item, ensure_ascii=False))
            else:
                item_type = getattr(item, "type", None)
                if item_type == "text":
                    parts.append(getattr(item, "text", ""))
                elif getattr(item, "text", None):
                    parts.append(item.text)
                else:
                    try:
                        parts.append(json.dumps(item.model_dump(), ensure_ascii=False))
                    except Exception:
                        parts.append(str(item))
        return "\n".join(part.strip() for part in parts if part and part.strip())

    if getattr(message, "refusal", None):
        return str(message.refusal).strip()

    return str(content or "").strip()


def response_has_images(response):
    message = response.choices[0].message
    return bool(getattr(message, "images", None))


def image_output_path(output_path, index):
    output_path = Path(output_path)
    return output_path if index == 0 else output_path.with_stem(f"{output_path.stem}_{index}")


def extract_image_result(response, output_path, image_index=0):
    message = response.choices[0].message
    output_path = Path(output_path)

    images = getattr(message, "images", None)
    if images:
        saved_paths = []
        for offset, image in enumerate(images):
            image_url = image.get("image_url", {}).get("url") if isinstance(image, dict) else None
            if image_url and ";base64," in image_url:
                b64_data = image_url.split(";base64,", 1)[1]
                dest = image_output_path(output_path, image_index + offset)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(base64.b64decode(b64_data))
                saved_paths.append(dest)
        if saved_paths:
            return [str(path) for path in saved_paths]

    content = getattr(message, "content", None) or ""
    if isinstance(content, list):
        content = extract_text_result(response)
    img_urls = re.findall(r"!\[.*?\]\((https?://[^\s)]+)\)", str(content))
    if img_urls:
        saved_paths = []
        output_path.parent.mkdir(parents=True, exist_ok=True)
        for offset, img_url in enumerate(img_urls):
            dest = image_output_path(output_path, image_index + offset)
            try:
                with urllib.request.urlopen(img_url, timeout=30) as remote:
                    dest.write_bytes(remote.read())
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                raise ValueError(f"下载图片失败: {img_url} ({exc})") from exc
            saved_paths.append(dest)
        return [str(path) for path in saved_paths]

    raise ValueError("未在响应中提取到图片")


def parse_search_replace_blocks(text):
    pattern = re.compile(
        r"<<<<<<< SEARCH\n(.*?)\n=======\n(.*?)\n>>>>>>> REPLACE",
        re.DOTALL,
    )
    matches = list(pattern.finditer(text.strip()))
    if not matches:
        fail("edit 模式要求模型仅输出 SEARCH/REPLACE diff blocks")

    normalized = []
    cursor = 0
    stripped_text = text.strip()
    for match in matches:
        extra = stripped_text[cursor:match.start()].strip()
        if extra:
            fail("edit 模式响应包含 diff block 之外的内容")
        search_text = match.group(1)
        replace_text = match.group(2)
        if not search_text:
            fail("edit 模式的 SEARCH 块不能为空")
        normalized.append((search_text, replace_text))
        cursor = match.end()
    if stripped_text[cursor:].strip():
        fail("edit 模式响应包含 diff block 之外的内容")
    return normalized


def apply_search_replace_blocks(source_text, diff_text):
    updated_text = source_text
    changed = False
    for search_text, replace_text in parse_search_replace_blocks(diff_text):
        occurrences = updated_text.count(search_text)
        if occurrences == 0:
            fail("edit 模式 diff 应用失败：SEARCH 内容未在原文中找到")
        if occurrences > 1:
            fail("edit 模式 diff 应用失败：SEARCH 内容在原文中出现多次，无法唯一定位")
        updated_text = updated_text.replace(search_text, replace_text, 1)
        changed = changed or (search_text != replace_text)
    if not changed:
        fail("edit 模式未产生有效修改")
    return updated_text


def write_text_output(output_path, text):
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")
    return str(path)


def default_output_path(mode, source_path=None):
    if mode == "image":
        target_dir = Path.cwd() / "gemini-output"
        target_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return str(target_dir / f"output_{timestamp}.jpg")
    if mode == "audio":
        if not source_path:
            fail("audio 模式缺少输入文件，无法推导默认输出路径")
        return str(Path(source_path).with_suffix(".srt"))
    return None
