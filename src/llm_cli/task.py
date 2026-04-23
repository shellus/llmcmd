import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .api import api_call, create_video_task, generate_tts_content, get_video_task
from .config import get_mode_concurrency
from .messages import DEFAULT_EDIT_PROMPT, build_messages
from .output import (
    apply_search_replace_blocks,
    default_output_path,
    extract_image_result,
    extract_text_result,
    extract_video_result,
    response_has_images,
    write_text_output,
    write_wav_output,
)
from .reference_transport import prepare_reference_resources
from .utils import read_input_files, read_text_file, resolve_path, resolve_text

VIDEO_POLL_INITIAL_DELAY_SECONDS = 30
VIDEO_POLL_INTERVAL_EARLY_SECONDS = 30
VIDEO_POLL_INTERVAL_LATE_SECONDS = 60
VIDEO_POLL_INTERVAL_SWITCH_SECONDS = 300
VIDEO_POLL_TIMEOUT_SECONDS = 1800


def _video_poll_delay(elapsed_seconds):
    if elapsed_seconds < VIDEO_POLL_INTERVAL_SWITCH_SECONDS:
        return VIDEO_POLL_INTERVAL_EARLY_SECONDS
    return VIDEO_POLL_INTERVAL_LATE_SECONDS


def _get_video_task_with_config(getter, client, task_id, config):
    try:
        return getter(client, task_id, config=config)
    except TypeError:
        return getter(client, task_id)


def _default_image_output_path(config):
    output_path = default_output_path("image")
    protocol = ((config or {}).get("mode") or {}).get("protocol") or "openai-chat-completions"
    if protocol == "openai-responses" and output_path:
        return str(Path(output_path).with_suffix(".png"))
    return output_path


def run_task(
    mode,
    client,
    model,
    *,
    messages=None,
    prompt=None,
    system_prompt=None,
    input_paths=None,
    reference=None,
    voice=None,
    output=None,
    temperature=None,
    max_output_tokens=None,
    base_dir=None,
    edit_path=None,
    image_count=1,
    config=None,
    progress_callback=None,
    stream_handler=None,
    image_size=None,
    image_aspect_ratio=None,
    video_seconds=None,
    video_size=None,
    resume_task_id=None,
):
    request_model = model
    if messages is None:
        prompt_text = resolve_text(prompt, base_dir=base_dir)
        system_text = resolve_text(system_prompt, base_dir=base_dir)
        input_text = read_input_files(input_paths or [], base_dir=base_dir)
    else:
        prompt_text = None
        system_text = None
        input_text = None

    edit_source_text = None
    edit_source_path = None
    effective_mode = mode
    if edit_path:
        edit_source_path = resolve_path(edit_path, base_dir=base_dir)
        edit_source_text = read_text_file(edit_path, base_dir=base_dir, missing_label="待编辑文件")
        system_text = system_text or DEFAULT_EDIT_PROMPT
        effective_mode = "chat_edit"
        input_text = read_input_files(input_paths or [], base_dir=base_dir)
        input_text = "\n\n".join(part for part in [edit_source_text, input_text] if part and part.strip())

    reference_path = None
    if reference and mode in {"image", "video"}:
        raw_references = list(reference) if isinstance(reference, (list, tuple)) else [reference]
        prepared_references = prepare_reference_resources(raw_references, config=config, base_dir=base_dir)
        reference_path = prepared_references["local_paths"]
        reference_urls = prepared_references["url_references"]
    elif reference:
        raw_references = list(reference) if isinstance(reference, (list, tuple)) else [reference]
        reference_path = [str(resolve_path(item, base_dir=base_dir)) for item in raw_references]
        reference_urls = []
    else:
        reference_urls = []
    if mode == "image" and reference:
        configured_edit_model = ((config or {}).get("model_config") or {}).get("edit_model")
        if configured_edit_model:
            request_model = configured_edit_model
    if messages is None and mode not in {"video", "tts"}:
        messages = build_messages(
            effective_mode,
            prompt=prompt_text,
            system_prompt=system_text,
            input_text=input_text,
            reference_path=reference_path,
            protocol=((config or {}).get("mode") or {}).get("protocol"),
            reference_urls=reference_urls,
        )

    extra_body = None
    if mode == "image":
        image_config = {}
        if image_size:
            image_config["image_size"] = image_size
        if image_aspect_ratio:
            image_config["aspect_ratio"] = image_aspect_ratio
        if image_config:
            extra_body = {
                "modalities": ["image", "text"],
                "image_config": image_config,
            }

    if mode == "tts":
        if not prompt_text:
            raise ValueError("tts 模式至少需要 prompt")
        output_path = output or default_output_path("tts")
        output_path = str(resolve_path(output_path, base_dir=base_dir)) if output else output_path
        response = generate_tts_content(
            client,
            model=request_model,
            prompt=prompt_text,
            voice=voice,
            config=config,
        )
        candidate = ((response or {}).get("candidates") or [{}])[0]
        content = candidate.get("content") or {}
        parts = content.get("parts") or []
        inline_data = None
        for part in parts:
            inline_data = part.get("inlineData") or part.get("inline_data")
            if inline_data:
                break
        if not inline_data:
            raise ValueError("tts 响应缺少 inlineData")
        audio_b64 = inline_data.get("data")
        if not audio_b64:
            raise ValueError("tts 响应缺少音频数据")
        pcm_bytes = __import__("base64").b64decode(audio_b64)
        saved_path = write_wav_output(output_path, pcm_bytes)
        return {"mode": mode, "output_path": saved_path, "printed": False}

    if mode == "video":
        output_path = output or default_output_path("video")
        output_path = str(resolve_path(output_path, base_dir=base_dir)) if output else output_path

        if resume_task_id:
            task_id = resume_task_id
            task = {"id": task_id, "status": "queued"}
        else:
            reference_file = reference_path[0] if reference_path else None
            task = create_video_task(
                client,
                model=model,
                prompt=prompt_text,
                seconds=video_seconds,
                size=video_size,
                input_reference=reference_file,
                reference_urls=reference_urls,
                config=config,
            )
            task_id = task.get("id") or task.get("task_id")
            if not task_id:
                raise ValueError(f"创建视频任务失败，响应缺少 id/task_id: {task}")
            if progress_callback:
                progress_callback("task_created", task_id=task_id, status=task.get("status"))

        terminal_success = {"succeeded", "completed", "success"}
        terminal_failed = {"failed", "error", "cancelled", "canceled"}
        task_status = str(task.get("status") or "").lower()
        waited_seconds = 0
        while task_status not in terminal_success:
            if task_status in terminal_failed:
                raise ValueError(f"视频任务失败: {task_id} ({task.get('status')})")
            if waited_seconds >= VIDEO_POLL_TIMEOUT_SECONDS:
                raise ValueError(f"视频任务等待超时: {task_id}（已等待 {waited_seconds} 秒）")
            delay_seconds = VIDEO_POLL_INITIAL_DELAY_SECONDS if waited_seconds == 0 else _video_poll_delay(waited_seconds)
            if progress_callback:
                progress_callback(
                    "poll",
                    task_id=task_id,
                    status=task.get("status"),
                    progress=task.get("progress"),
                    waited_seconds=waited_seconds,
                    next_delay_seconds=delay_seconds,
                )
            time.sleep(delay_seconds)
            waited_seconds += delay_seconds
            task = _get_video_task_with_config(get_video_task, client, task_id, config)
            task_status = str(task.get("status") or "").lower()

        task = dict(task)
        task["_client"] = client
        task["_config"] = config
        if progress_callback:
            progress_callback("task_completed", task_id=task_id, status=task.get("status"))
        saved_paths = extract_video_result(task, output_path, task_id=task_id, progress_callback=progress_callback)
        return {"mode": mode, "output_paths": saved_paths, "task_id": task_id, "printed": False}

    response = api_call(
        client,
        request_model,
        messages,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        stream_handler=stream_handler,
        extra_body=extra_body,
        config=config,
    )

    if mode == "image":
        output_path = output or _default_image_output_path(config)
        output_path = str(resolve_path(output_path, base_dir=base_dir)) if output else output_path
        if image_count == 1:
            saved_paths = extract_image_result(response, output_path, config=config)
            return {"mode": mode, "output_paths": saved_paths, "printed": False}

        concurrency = get_mode_concurrency("image", config or {})
        max_workers = min(image_count, concurrency)
        if progress_callback:
            progress_callback("start", total=image_count, concurrency=max_workers)

        def render_one(index):
            image_response = response if index == 0 else api_call(
                client,
                request_model,
                messages,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                extra_body=extra_body,
                config=config,
            )
            return extract_image_result(image_response, output_path, image_index=index, config=config)

        saved_paths = []
        completed = 0
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(render_one, index): index for index in range(image_count)}
            ordered = {}
            for future in as_completed(futures):
                index = futures[future]
                ordered[index] = future.result()
                completed += 1
                if progress_callback:
                    progress_callback("progress", completed=completed, total=image_count, index=index)
        for index in range(image_count):
            saved_paths.extend(ordered[index])
        if progress_callback:
            progress_callback("done", total=image_count, paths=saved_paths)
        return {"mode": mode, "output_paths": saved_paths, "printed": False}

    if mode in {"chat", "text"} and response_has_images(response):
        output_path = output or _default_image_output_path(config)
        output_path = str(resolve_path(output_path, base_dir=base_dir)) if output else output_path
        saved_paths = extract_image_result(response, output_path, config=config)
        return {"mode": mode, "output_paths": saved_paths, "printed": False}

    text = extract_text_result(response)
    if edit_source_path:
        updated_text = apply_search_replace_blocks(edit_source_text, text)
        target_path = output or str(edit_source_path)
        saved_path = write_text_output(resolve_path(target_path, base_dir=base_dir), updated_text)
        return {
            "mode": mode,
            "text": updated_text,
            "output_path": saved_path,
            "printed": False,
            "edit_diff": text,
        }

    if output:
        output_path = str(resolve_path(output, base_dir=base_dir))
        saved_path = write_text_output(output_path, text)
        return {"mode": mode, "text": text, "output_path": saved_path, "printed": False}

    return {"mode": mode, "text": text, "printed": True}
