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


def _debug_json(value):
    return json.dumps(sanitize_debug_value(value), ensure_ascii=False, separators=(", ", ": "))


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
    body = getattr(request, "data", None)
    if DEBUG:
        if body:
            try:
                parsed = json.loads(body.decode("utf-8"))
                debug_log(f"{request.get_method()} {request.full_url} body={_debug_json(parsed)}")
            except Exception:
                debug_log(f"{request.get_method()} {request.full_url} body=<{len(body)} bytes>")
        else:
            debug_log(f"{request.get_method()} {request.full_url}")
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        if DEBUG:
            error_body = exc.read().decode("utf-8", "replace")
            try:
                debug_log(f"{exc.code} {request.get_method()} {request.full_url} error={_debug_json(json.loads(error_body))}")
            except json.JSONDecodeError:
                debug_log(f"{exc.code} {request.get_method()} {request.full_url} error={repr(error_body[:1000])}")
        raise
    if DEBUG:
        try:
            debug_log(f"{getattr(response, 'status', 200)} {request.get_method()} {request.full_url} -> {_debug_json(json.loads(payload))}")
        except json.JSONDecodeError:
            debug_log(f"{getattr(response, 'status', 200)} {request.get_method()} {request.full_url} -> {repr(payload[:500])}")
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
    resolved_seconds = seconds or request_options.get("seconds") or mode_defaults.get("seconds")
    resolved_size = size or request_options.get("size") or mode_defaults.get("size")
    resolved_aspect_ratio = request_options.get("aspect_ratio") or mode_defaults.get("aspect_ratio")
    uploaded_reference_urls = list(reference_urls or [])
    if protocol == "unified-video":
        if uploaded_reference_urls:
            reference_transport = "uploaded_url"
        elif input_reference:
            reference_transport = "data_url"
        else:
            reference_transport = "none"
    else:
        reference_transport = "multipart_file" if input_reference else "none"

    if DEBUG:
        debug_log(
            "视频创建摘要:",
            _debug_json(
                {
                    "protocol": protocol,
                    "model": model,
                    "seconds": resolved_seconds,
                    "size": resolved_size,
                    "aspect_ratio": resolved_aspect_ratio,
                    "reference_input_mode": reference_transport,
                    "reference_url_available": bool(uploaded_reference_urls),
                    "reference_url_count": len(uploaded_reference_urls),
                    "input_reference": Path(input_reference).name if input_reference else None,
                }
            ),
        )

    if protocol == "unified-video":
        body = {
            "model": model,
            "prompt": prompt,
            "images": uploaded_reference_urls,
        }
        if resolved_seconds is not None:
            body["seconds"] = resolved_seconds
        if resolved_size is not None:
            body["size"] = resolved_size
        if resolved_aspect_ratio is not None:
            body["aspect_ratio"] = resolved_aspect_ratio
        if not body["images"] and input_reference:
            try:
                body["images"] = [_as_data_url(input_reference)]
            except OSError as exc:
                raise ValueError(f"读取视频参考图失败: {input_reference} ({exc})") from exc
        headers = _json_headers(client)
        headers["Content-Type"] = "application/json"
        return _json_body_request(f"{_client_base_url(client)}/video/create", body, headers, "POST")

    boundary, body = _multipart_body(
        {
            "model": model,
            "prompt": prompt,
            "seconds": resolved_seconds,
            "size": resolved_size,
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
        debug_log(f"DOWNLOAD {request.get_method()} {request.full_url}")
    with urllib.request.urlopen(request, timeout=300) as response:
        if DEBUG:
            debug_log(
                f"DOWNLOAD {getattr(response, 'status', 200)} {request.full_url} headers="
                + _debug_json(
                    {
                        "Content-Type": response.headers.get("Content-Type"),
                        "Content-Length": response.headers.get("Content-Length"),
                        "Cache-Control": response.headers.get("Cache-Control"),
                    }
                )
            )
        while True:
            chunk = response.read(chunk_size)
            if not chunk:
                break
            yield chunk


def api_call(client, model, messages, temperature=None, max_output_tokens=None, stream_handler=None, extra_body=None, config=None):
    protocol = ((config or {}).get("mode") or {}).get("protocol") or "openai-chat-completions"
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
    kwargs["stream"] = protocol != "grok2api-image"

    if DEBUG:
        debug_kwargs = sanitize_debug_value(kwargs)
        debug_log(f"{request_method} {request_url} body={_debug_json(debug_kwargs)}")

    stream = client.chat.completions.create(**kwargs)

    if not kwargs["stream"]:
        if hasattr(stream, "choices"):
            return stream
        try:
            collected = list(stream)
        except TypeError:
            return stream
        if collected and hasattr(collected[-1], "choices"):
            return SimpleNamespace(choices=[SimpleNamespace(message=collected[-1].choices[0].message)])
        return _finalize_stream_response([], [], [])

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
        debug_log(
            "STREAM done "
            + _debug_json(
                {
                    "content": full_content[:500],
                    "images": image_parts[:1] if image_parts else None,
                    "refusal": "".join(refusal_parts).strip() or None,
                }
            )
        )
    return _finalize_stream_response(content_parts, image_parts, refusal_parts)
