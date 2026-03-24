from pathlib import Path

from .files import is_image_attachment, is_text_attachment, load_binary_attachment, read_text_attachment
from .utils import fail, join_message_parts

DEFAULT_EDIT_PROMPT = """你是一个严谨的文本编辑助手。你会收到一份原始文件内容，以及用户的修改要求。

请严格遵守以下规则：
- 仅输出 SEARCH/REPLACE diff blocks，不要输出解释、标题、文件名、Markdown 代码块
- 每个修改块必须使用以下格式：
<<<<<<< SEARCH
需要被替换的原文
=======
替换后的新内容
>>>>>>> REPLACE
- SEARCH 内容必须与原文件中的连续文本完全一致
- 只做满足用户要求的最小修改，不要改动无关内容
- SEARCH 必须足够精确，以便在原文中唯一定位
- 可以输出多个修改块；若只需一处修改，只输出一个修改块
- 必须给出至少一个实际修改；不要输出空响应，也不要输出与原文完全相同的替换
"""


def _build_file_part(path):
    attachment = load_binary_attachment(path)
    return {
        "type": "file",
        "file": {
            "filename": Path(attachment["path"]).name,
            "file_data": attachment["base64_data"],
        },
    }


def _build_image_url_part(path):
    attachment = load_binary_attachment(path, "image")
    return {
        "type": "image_url",
        "image_url": {
            "url": f"data:{attachment['mime_type']};base64,{attachment['base64_data']}"
        },
    }


def _build_text_attachment_part(path):
    attachment = read_text_attachment(path)
    filename = Path(attachment["path"]).name
    language = attachment["language"]
    content = attachment["content"]
    body = f"[文件: {filename}]\n```{language}\n{content}\n```" if content else f"[文件: {filename}]"
    return {"type": "text", "text": body}


def build_messages(mode, prompt, system_prompt=None, input_text=None, reference_path=None, audio_path=None):
    if reference_path is None:
        reference_paths = []
    elif isinstance(reference_path, (list, tuple)):
        reference_paths = list(reference_path)
    else:
        reference_paths = [reference_path]

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    if mode == "chat_edit":
        if not input_text:
            fail("edit 模式需要目标文件内容")
        instruction = prompt or "按用户要求修改文件内容"
        user_parts = [
            f"# 修改要求\n\n{instruction}",
            f"# 原始文件内容\n\n{input_text}",
        ]
        content = [{"type": "text", "text": join_message_parts(*user_parts)}]
        for path in reference_paths:
            if is_image_attachment(path):
                content.append(_build_image_url_part(path))
            elif is_text_attachment(path):
                content.append(_build_text_attachment_part(path))
            else:
                fail(f"chat edit 模式暂不支持该附件类型: {path}")
        messages.append({"role": "user", "content": content})
        return messages

    message_text = join_message_parts(prompt, input_text)
    if mode in {"chat", "text"}:
        if not message_text and not reference_paths:
            fail("chat 模式至少需要 prompt、input 或 reference")
        if reference_paths:
            content = []
            if message_text:
                content.append({"type": "text", "text": message_text})
            for path in reference_paths:
                if is_image_attachment(path):
                    content.append(_build_image_url_part(path))
                elif is_text_attachment(path):
                    content.append(_build_text_attachment_part(path))
                else:
                    fail(f"chat 模式暂不支持该附件类型: {path}")
            messages.append({"role": "user", "content": content})
        else:
            messages.append({"role": "user", "content": message_text})
        return messages

    if mode == "image":
        if not message_text:
            fail("image 模式至少需要 prompt")
        if reference_paths:
            content = []
            for path in reference_paths:
                content.append(_build_file_part(path))
            content.append({"type": "text", "text": message_text})
            messages.append({"role": "user", "content": content})
        else:
            messages.append({"role": "user", "content": message_text})
        return messages

    if mode == "audio":
        if not audio_path:
            fail("audio 模式需要 audio_file 文件")
        attachment = load_binary_attachment(audio_path, "audio")
        # 使用 file type 而非 input_audio，因为 cliproxy 的 gemini translator 支持 file
        filename = Path(audio_path).name
        content = [
            {
                "type": "file",
                "file": {
                    "filename": filename,
                    "file_data": attachment["base64_data"],
                },
            }
        ]
        if message_text:
            content.append({"type": "text", "text": message_text})
        messages.append({"role": "user", "content": content})
        return messages

    fail(f"不支持的 mode: {mode}")
