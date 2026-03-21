import json
import sys

DEBUG = False


def set_debug(value):
    global DEBUG
    DEBUG = bool(value)


def debug_log(*args, **kwargs):
    if DEBUG:
        print("[DEBUG]", *args, **kwargs, file=sys.stderr)


def api_call(client, model, messages, temperature=None, max_output_tokens=None):
    kwargs = {
        "model": model,
        "messages": messages,
    }
    request_method = "POST"
    request_url = str(client.base_url).rstrip("/") + "/chat/completions"
    if temperature is not None:
        kwargs["temperature"] = temperature
    if max_output_tokens is not None:
        kwargs["max_tokens"] = max_output_tokens

    if DEBUG:
        import copy
        debug_kwargs = copy.deepcopy(kwargs)
        # 截断 base64 数据避免刷屏
        for msg in debug_kwargs.get("messages", []):
            content = msg.get("content")
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict):
                        for key in ("file", "input_audio", "image_url"):
                            if key in item:
                                sub = item[key]
                                if isinstance(sub, dict):
                                    for field in ("file_data", "data", "url"):
                                        if field in sub and len(str(sub[field])) > 100:
                                            sub[field] = sub[field][:50] + f"...<truncated, total {len(sub[field])} chars>"
        debug_log("请求方法:", request_method)
        debug_log("请求 URL:", request_url)
        debug_log("请求参数:", json.dumps(debug_kwargs, ensure_ascii=False, indent=2))

    try:
        response = client.chat.completions.create(**kwargs)
        if DEBUG:
            msg = response.choices[0].message
            debug_log("响应 content:", repr((getattr(msg, "content", None) or "")[:500]))
            debug_log("响应 images:", getattr(msg, "images", None))
        return response
    except json.JSONDecodeError:
        # 上游返回 SSE 流式，fallback 到 stream=True
        debug_log("JSONDecodeError，fallback 到 stream=True")
        kwargs["stream"] = True
        stream = client.chat.completions.create(**kwargs)

        content_parts = []
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                content_parts.append(chunk.choices[0].delta.content)

        full_content = "".join(content_parts)
        if DEBUG:
            debug_log("流式收集 content:", repr(full_content[:500]))

        # 构造兼容响应对象
        class FakeMessage:
            def __init__(self, content):
                self.content = content
                self.images = None

        class FakeChoice:
            def __init__(self, message):
                self.message = message

        class FakeResponse:
            def __init__(self, content):
                self.choices = [FakeChoice(FakeMessage(content))]

        return FakeResponse(full_content)
