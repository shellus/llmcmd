import json
import sys
import copy
from types import SimpleNamespace

DEBUG = False


def set_debug(value):
    global DEBUG
    DEBUG = bool(value)


def debug_log(*args, **kwargs):
    if DEBUG:
        print("[DEBUG]", *args, **kwargs, file=sys.stderr)


def _model_to_dict(value):
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump()
    return None


def _finalize_stream_response(content_parts, image_parts, refusal_parts):
    message = SimpleNamespace(
        content="".join(content_parts),
        images=image_parts or None,
        refusal="".join(refusal_parts).strip() or None,
    )
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice])


def sanitize_debug_value(value, *, limit=100):
    cloned = copy.deepcopy(value)

    def walk(node):
        if isinstance(node, dict):
            for key, sub in list(node.items()):
                if key in {"file_data", "data", "url"} and len(str(sub)) > limit:
                    node[key] = str(sub)[:50] + f"...<truncated, total {len(str(sub))} chars>"
                else:
                    walk(sub)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(cloned)
    return cloned


def api_call(client, model, messages, temperature=None, max_output_tokens=None, stream_handler=None):
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
    kwargs["stream"] = True

    if DEBUG:
        debug_kwargs = sanitize_debug_value(kwargs)
        debug_log("请求方法:", request_method)
        debug_log("请求 URL:", request_url)
        debug_log("请求参数:", json.dumps(debug_kwargs, ensure_ascii=False, indent=2))

    stream = client.chat.completions.create(**kwargs)

    content_parts = []
    image_parts = []
    refusal_parts = []
    for chunk in stream:
        if not getattr(chunk, "choices", None):
            continue
        delta = chunk.choices[0].delta
        content = getattr(delta, "content", None)
        if content is not None:
            content_parts.append(content)
            if content and stream_handler:
                stream_handler(content)
        refusal = getattr(delta, "refusal", None)
        if refusal:
            refusal_parts.append(str(refusal))
        images = getattr(delta, "images", None)
        if images:
            for image in images:
                image_parts.append(_model_to_dict(image) or image)

    full_content = "".join(content_parts)
    if DEBUG:
        debug_log("流式收集 content:", repr(full_content[:500]))
        debug_log("流式收集 images:", sanitize_debug_value(image_parts[:1] if image_parts else None))
    return _finalize_stream_response(content_parts, image_parts, refusal_parts)
