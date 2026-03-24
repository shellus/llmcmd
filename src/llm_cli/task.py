from concurrent.futures import ThreadPoolExecutor, as_completed

from .api import api_call
from .config import get_mode_concurrency
from .messages import DEFAULT_EDIT_PROMPT, build_messages
from .output import apply_search_replace_blocks, default_output_path, extract_image_result, extract_text_result, response_has_images, write_text_output
from .utils import read_input_files, read_text_file, resolve_path, resolve_text


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
    audio_file=None,
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
):
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
    if reference:
        if isinstance(reference, (list, tuple)):
            reference_path = [str(resolve_path(item, base_dir=base_dir)) for item in reference]
        else:
            reference_path = [str(resolve_path(reference, base_dir=base_dir))]
    audio_path = None
    if audio_file:
        audio_path = str(resolve_path(audio_file, base_dir=base_dir))

    if messages is None:
        messages = build_messages(
            effective_mode,
            prompt=prompt_text,
            system_prompt=system_text,
            input_text=input_text,
            reference_path=reference_path,
            audio_path=audio_path,
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

    response = api_call(
        client,
        model,
        messages,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        stream_handler=stream_handler,
        extra_body=extra_body,
    )

    if mode == "image":
        output_path = output or default_output_path("image")
        output_path = str(resolve_path(output_path, base_dir=base_dir)) if output else output_path
        if image_count == 1:
            saved_paths = extract_image_result(response, output_path)
            return {"mode": mode, "output_paths": saved_paths, "printed": False}

        concurrency = get_mode_concurrency("image", config or {})
        max_workers = min(image_count, concurrency)
        if progress_callback:
            progress_callback("start", total=image_count, concurrency=max_workers)

        def render_one(index):
            image_response = response if index == 0 else api_call(
                client,
                model,
                messages,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                extra_body=extra_body,
            )
            return extract_image_result(image_response, output_path, image_index=index)

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
        output_path = output or default_output_path("image")
        output_path = str(resolve_path(output_path, base_dir=base_dir)) if output else output_path
        saved_paths = extract_image_result(response, output_path)
        return {"mode": mode, "output_paths": saved_paths, "printed": False}

    text = extract_text_result(response)
    if mode == "audio":
        if output:
            output_path = str(resolve_path(output, base_dir=base_dir))
            saved_path = write_text_output(output_path, text)
            return {"mode": mode, "text": text, "output_path": saved_path, "printed": False}
        return {"mode": mode, "text": text, "printed": True}

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
