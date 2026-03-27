import copy
import base64
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

DEBUG = False
DEFAULT_USER_AGENT = "curl/8.5.0"


def _video_user_agent():
    return os.getenv("USER_AGENT") or DEFAULT_USER_AGENT


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


def _client_base_url(client):
    return str(client.base_url).rstrip("/")


def _client_api_key(client):
    api_key = getattr(client, "api_key", None)
    if callable(api_key):
        api_key = api_key()
    if not api_key:
        raise ValueError("video 模式缺少 API Key")
    return api_key


def _json_headers(client):
    return {
        "Authorization": f"Bearer {_client_api_key(client)}",
        "Accept": "application/json",
        "User-Agent": _video_user_agent(),
    }


def _json_body_request(url, body, headers, method):
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method=method,
    )
    return _json_request(request)


def _multipart_body(fields, files):
    boundary = f"----llmcmd-{uuid4().hex}"
    chunks = []

    for name, value in fields.items():
        if value is None:
            continue
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"),
                str(value).encode("utf-8"),
                b"\r\n",
            ]
        )

    for name, path in files.items():
        if not path:
            continue
        file_path = Path(path)
        mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                (
                    f'Content-Disposition: form-data; name="{name}"; filename="{file_path.name}"\r\n'
                    f"Content-Type: {mime_type}\r\n\r\n"
                ).encode("utf-8"),
                file_path.read_bytes(),
                b"\r\n",
            ]
        )

    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return boundary, b"".join(chunks)


def _json_request(request):
    if DEBUG:
        debug_log("视频请求方法:", request.get_method())
        debug_log("视频请求 URL:", request.full_url)
        body = getattr(request, "data", None)
        if body:
            try:
                parsed = json.loads(body.decode("utf-8"))
                debug_log("视频请求体:", json.dumps(sanitize_debug_value(parsed), ensure_ascii=False, indent=2))
            except Exception:
                debug_log("视频请求体摘要:", f"<{len(body)} bytes>")
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        if DEBUG:
            debug_log("视频错误状态:", exc.code)
            debug_log("视频错误响应头:", json.dumps(dict(exc.headers.items()), ensure_ascii=False, indent=2))
            error_body = exc.read().decode("utf-8", "replace")
            try:
                debug_log("视频错误响应体:", json.dumps(sanitize_debug_value(json.loads(error_body)), ensure_ascii=False, indent=2))
            except json.JSONDecodeError:
                debug_log("视频错误响应体:", repr(error_body[:1000]))
        raise
    if DEBUG:
        try:
            debug_log("视频响应:", json.dumps(sanitize_debug_value(json.loads(payload)), ensure_ascii=False, indent=2))
        except json.JSONDecodeError:
            debug_log("视频响应:", repr(payload[:500]))
    return json.loads(payload)


def _as_data_url(path):
    file_path = Path(path)
    mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    return f"data:{mime_type};base64,{base64.b64encode(file_path.read_bytes()).decode('ascii')}"


def create_video_task(
    client,
    *,
    model,
    prompt=None,
    seconds=None,
    size=None,
    input_reference=None,
    reference_urls=None,
    config=None,
):
    protocol = ((config or {}).get("mode") or {}).get("protocol") or "openai-videos"
    mode_defaults = ((config or {}).get("mode") or {}).get("defaults") or {}
    request_options = ((config or {}).get("mode") or {}).get("request") or {}

    if protocol == "unified-video":
        body = {
            "model": model,
            "prompt": prompt,
            "aspect_ratio": request_options.get("aspect_ratio") or mode_defaults.get("aspect_ratio"),
            "size": size or request_options.get("size") or mode_defaults.get("size"),
            "images": list(reference_urls or []),
        }
        if not body["images"] and input_reference:
            try:
                body["images"] = [_as_data_url(input_reference)]
            except OSError as exc:
                raise ValueError(f"读取视频参考图失败: {input_reference} ({exc})") from exc
        headers = _json_headers(client)
        headers["Content-Type"] = "application/json"
        return _json_body_request(f"{_client_base_url(client)}/video/create", body, headers, "POST")

    if DEBUG:
        debug_log(
            "视频请求体摘要:",
            json.dumps(
                {
                    "model": model,
                    "prompt": prompt,
                    "seconds": seconds,
                    "size": size,
                    "input_reference": Path(input_reference).name if input_reference else None,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )

    boundary, body = _multipart_body(
        {
            "model": model,
            "prompt": prompt,
            "seconds": seconds,
            "size": size,
        },
        {
            "input_reference": input_reference,
        },
    )
    headers = _json_headers(client)
    headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    request = urllib.request.Request(
        f"{_client_base_url(client)}/videos",
        data=body,
        headers=headers,
        method="POST",
    )
    return _json_request(request)


def get_video_task(client, task_id, config=None):
    protocol = ((config or {}).get("mode") or {}).get("protocol") or "openai-videos"
    if protocol == "unified-video":
        request = urllib.request.Request(
            f"{_client_base_url(client)}/video/query?id={urllib.parse.quote(str(task_id))}",
            headers=_json_headers(client),
            method="GET",
        )
        return _json_request(request)
    request = urllib.request.Request(
        f"{_client_base_url(client)}/videos/{urllib.parse.quote(str(task_id))}",
        headers=_json_headers(client),
        method="GET",
    )
    return _json_request(request)


def download_video_content(client, task_id):
    request = urllib.request.Request(
        f"{_client_base_url(client)}/videos/{urllib.parse.quote(str(task_id))}/content",
        headers={
            "Authorization": f"Bearer {_client_api_key(client)}",
            "User-Agent": _video_user_agent(),
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        return response.read()


def download_video_content_stream(client, task_id, chunk_size=1024 * 256, config=None, task=None):
    protocol = ((config or {}).get("mode") or {}).get("protocol") or "openai-videos"
    if protocol == "unified-video":
        video_url = (task or {}).get("video_url")
        if not video_url:
            raise ValueError("视频任务缺少 video_url，无法下载")
        request = urllib.request.Request(
            video_url,
            headers={"User-Agent": _video_user_agent()},
            method="GET",
        )
    else:
        request = urllib.request.Request(
            f"{_client_base_url(client)}/videos/{urllib.parse.quote(str(task_id))}/content",
            headers={
                "Authorization": f"Bearer {_client_api_key(client)}",
                "User-Agent": _video_user_agent(),
            },
            method="GET",
        )
    if DEBUG:
        debug_log("视频下载请求方法:", request.get_method())
        debug_log("视频下载 URL:", request.full_url)
    with urllib.request.urlopen(request, timeout=300) as response:
        if DEBUG:
            debug_log("视频下载响应头:", json.dumps(dict(response.headers.items()), ensure_ascii=False, indent=2))
        while True:
            chunk = response.read(chunk_size)
            if not chunk:
                break
            yield chunk


def api_call(client, model, messages, temperature=None, max_output_tokens=None, stream_handler=None, extra_body=None):
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
    if extra_body:
        kwargs["extra_body"] = extra_body
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
