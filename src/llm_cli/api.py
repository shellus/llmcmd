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


def _truncate_text(value, limit=240):
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + f"...<truncated, total {len(text)} chars>"


def _responses_event_preview(data, limit=240):
    return _truncate_text(" ".join(str(data or "").split()), limit=limit)


def _responses_event_error_summary(event):
    candidates = [
        event.get("error"),
        (event.get("response") or {}).get("error"),
        (event.get("item") or {}).get("error"),
    ]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        error_type = str(candidate.get("type") or "").strip()
        message = str(candidate.get("message") or candidate.get("code") or "").strip()
        if error_type and message:
            return f"{error_type}: {message}"
        if message:
            return message
        if error_type:
            return error_type
    return ""


def sanitize_debug_value(value, *, limit=100):
    cloned = copy.deepcopy(value)

    def walk(node):
        if isinstance(node, dict):
            for key, sub in list(node.items()):
                if key in {"file_data", "data", "url", "image_url", "result"} and isinstance(sub, str) and len(sub) > limit:
                    node[key] = sub[:50] + f"...<truncated, total {len(sub)} chars>"
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


def generate_tts_content(client, *, model, prompt, voice=None, config=None):
    base_url = _client_base_url(client)
    if base_url.endswith("/v1"):
        base_url = base_url[:-3]
    model_path = str(model).lstrip("/")
    if model_path.startswith("v1beta/"):
        url = f"{base_url}/{model_path}:generateContent"
    else:
        url = f"{base_url}/v1beta/models/{model_path}:generateContent"

    body = {
        "model": model,
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
        },
    }
    if voice:
        body["generationConfig"]["speechConfig"] = {
            "voiceConfig": {
                "prebuiltVoiceConfig": {
                    "voiceName": voice,
                }
            }
        }

    headers = {
        "x-goog-api-key": _client_api_key(client),
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": _video_user_agent(),
    }
    return _json_body_request(url, body, headers, "POST")


def _responses_input_part(part):
    if isinstance(part, str):
        return {"type": "input_text", "text": part}

    if not isinstance(part, dict):
        return {"type": "input_text", "text": str(part)}

    part_type = part.get("type")
    if part_type == "text":
        return {"type": "input_text", "text": part.get("text", "")}

    if part_type == "image_url":
        image_url = part.get("image_url")
        if isinstance(image_url, dict):
            image_url = image_url.get("url")
        return {"type": "input_image", "image_url": image_url}

    if part_type == "file":
        file_payload = part.get("file") or {}
        mime_type = str(file_payload.get("mime_type") or "")
        file_data = file_payload.get("file_data")
        if mime_type.startswith("image/") and file_data:
            return {"type": "input_image", "image_url": file_data}
        input_file = {"type": "input_file"}
        if file_payload.get("filename"):
            input_file["filename"] = file_payload["filename"]
        if file_data:
            input_file["file_data"] = file_data
        return input_file

    return part


def _messages_to_responses_payload(messages):
    instructions = []
    input_items = []

    for message in messages or []:
        role = message.get("role") or "user"
        content = message.get("content")

        if role == "system":
            if isinstance(content, list):
                instructions.extend(
                    str(part.get("text") or "") for part in content if isinstance(part, dict) and part.get("type") == "text"
                )
            elif content is not None:
                instructions.append(str(content))
            continue

        if isinstance(content, list):
            normalized_content = [_responses_input_part(part) for part in content]
        elif content is None:
            normalized_content = []
        else:
            normalized_content = [{"type": "input_text", "text": str(content)}]

        input_items.append({"role": role, "content": normalized_content})

    payload = {"input": input_items}
    joined_instructions = "\n\n".join(part for part in instructions if part and part.strip()).strip()
    if joined_instructions:
        payload["instructions"] = joined_instructions
    return payload


def _iter_sse_events(response):
    event_name = None
    data_lines = []

    def line_iter():
        if hasattr(response, "readline"):
            while True:
                raw_line = response.readline()
                if not raw_line:
                    break
                yield raw_line
            return
        for raw_line in response:
            yield raw_line

    for raw_line in line_iter():
        line = raw_line.decode("utf-8", "replace").rstrip("\r\n")
        if not line:
            if event_name is not None or data_lines:
                yield event_name, "\n".join(data_lines)
            event_name = None
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line.split(":", 1)[1].strip()
            continue
        if line.startswith("data:"):
            data_lines.append(line.split(":", 1)[1].lstrip())

    if event_name is not None or data_lines:
        yield event_name, "\n".join(data_lines)


def _extract_responses_text(event, *, allow_terminal_text):
    event_type = event.get("type")
    if event_type == "response.output_text.delta":
        return str(event.get("delta") or "")
    if event_type == "response.output_text.done" and allow_terminal_text:
        text = event.get("text")
        if text is not None:
            return str(text)
        item = event.get("item") or {}
        if item.get("text") is not None:
            return str(item.get("text"))
        part = event.get("part") or {}
        if part.get("text") is not None:
            return str(part.get("text"))
    if event_type == "response.content_part.done" and allow_terminal_text:
        part = event.get("part") or {}
        if part.get("type") in {"output_text", "text"} and part.get("text") is not None:
            return str(part.get("text"))
    return None


def _responses_api_call(client, model, messages, *, stream_handler=None):
    request_url = f"{_client_base_url(client)}/responses"
    body = {
        "model": model,
        "stream": True,
        **_messages_to_responses_payload(messages),
    }
    headers = {
        "Authorization": f"Bearer {_client_api_key(client)}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "User-Agent": _video_user_agent(),
    }
    request = urllib.request.Request(
        request_url,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    if DEBUG:
        debug_log(f"POST {request_url} body={_debug_json(sanitize_debug_value(body))}")

    content_parts = []
    image_parts = []
    refusal_parts = []
    saw_output_text_delta = False
    saw_done = False
    saw_completed = False
    event_count = 0
    last_event_type = None
    last_event_preview = None

    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            content_type = response.headers.get("Content-Type", "")
            for event_name, data in _iter_sse_events(response):
                if not data:
                    continue
                if data == "[DONE]":
                    saw_done = True
                    last_event_type = "[DONE]"
                    last_event_preview = "[DONE]"
                    break
                event_count += 1
                last_event_type = event_name or last_event_type or "unknown"
                last_event_preview = _responses_event_preview(data)
                try:
                    event = json.loads(data)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"Responses SSE 事件解析失败：{exc}；last_event={last_event_type or 'unknown'}；data预览={last_event_preview or '<empty>'}"
                    ) from exc
                event_type = event.get("type") or event_name or "unknown"
                last_event_type = event_type

                if event_type in {"response.failed", "response.error"}:
                    error_summary = _responses_event_error_summary(event) or last_event_preview or event_type
                    raise ValueError(f"Responses 上游失败：{error_summary}")

                text = _extract_responses_text(event, allow_terminal_text=not saw_output_text_delta)
                if event_type == "response.output_text.delta":
                    saw_output_text_delta = True
                if text:
                    content_parts.append(text)
                    if stream_handler:
                        stream_handler(text)

                if event_type == "response.completed":
                    saw_completed = True

                if event_type == "response.output_item.done":
                    item = event.get("item") or {}
                    if item.get("type") == "image_generation_call" and item.get("result"):
                        image_part = {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{item['result']}"},
                        }
                        if item.get("revised_prompt"):
                            image_part["revised_prompt"] = item["revised_prompt"]
                        image_parts.append(image_part)
    except urllib.error.HTTPError as exc:
        if DEBUG:
            error_body = exc.read().decode("utf-8", "replace")
            try:
                debug_log(f"{exc.code} POST {request_url} error={_debug_json(json.loads(error_body))}")
            except json.JSONDecodeError:
                debug_log(f"{exc.code} POST {request_url} error={repr(error_body[:1000])}")
        raise

    if not saw_completed and not image_parts:
        end_reason = "[DONE]" if saw_done else "EOF"
        raise ValueError(
            f"Responses 流提前结束：连接以 {end_reason} 结束，未收到 response.completed；last_event={last_event_type or 'unknown'}；events={event_count}"
        )

    full_content = "".join(content_parts)
    if DEBUG:
        debug_log(
            "STREAM done "
            + _debug_json(
                {
                    "content_type": content_type,
                    "events": event_count,
                    "last_event": last_event_type,
                    "content": full_content[:500],
                    "images": image_parts[:1] if image_parts else None,
                    "refusal": "".join(refusal_parts).strip() or None,
                }
            )
        )
    return _finalize_stream_response(content_parts, image_parts, refusal_parts)


def api_call(client, model, messages, temperature=None, max_output_tokens=None, stream_handler=None, extra_body=None, config=None):
    protocol = ((config or {}).get("mode") or {}).get("protocol") or "openai-chat-completions"
    if protocol == "openai-responses":
        return _responses_api_call(client, model, messages, stream_handler=stream_handler)

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
