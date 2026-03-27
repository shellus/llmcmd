import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from .config import create_client, get_config_value
from .task import run_task
from .utils import IMAGE_ASPECT_CHOICES, IMAGE_SIZE_CHOICES, MODE_ALIASES, fail, resolve_path

try:
    import yaml
except ImportError:
    yaml = None
    YAMLError = Exception


def ensure_yaml_available():
    if yaml is None:
        fail("batch 模式需要 pyyaml: pip install pyyaml")


def normalize_mode(value, field_name="mode"):
    if value == "text":
        value = "chat"
    if value not in MODE_ALIASES:
        fail(f"{field_name} 必须是 chat / image / audio / video，当前为: {value}")
    return value


def normalize_task_input(raw_input, index):
    if raw_input is None:
        return []
    if isinstance(raw_input, str):
        return [raw_input]
    if isinstance(raw_input, list) and all(isinstance(item, str) for item in raw_input):
        return raw_input
    fail(f"第 {index} 个 task 的 input 必须是字符串或字符串数组")


def validate_task_fields(mode, task, index):
    if mode == "chat":
        if not task.get("prompt") and not task.get("input_paths") and not task.get("reference") and not task.get("edit_path"):
            fail(f"第 {index} 个 chat task 缺少 prompt、input、reference 或 edit")
        if task.get("audio_file"):
            fail(f"第 {index} 个 chat task 不支持 audio_file")
    elif mode == "image":
        if not task.get("prompt"):
            fail(f"第 {index} 个 image task 缺少 prompt")
        if task.get("audio_file"):
            fail(f"第 {index} 个 image task 不支持 audio_file")
        count = task.get("count", 1)
        if not isinstance(count, int) or count <= 0:
            fail(f"第 {index} 个 image task 的 count 必须是大于 0 的整数")
        image_size = task.get("image_size")
        if image_size is not None and image_size not in IMAGE_SIZE_CHOICES:
            fail(f"第 {index} 个 image task 的 size 必须是 {', '.join(IMAGE_SIZE_CHOICES)}，当前为: {image_size}")
        image_aspect_ratio = task.get("image_aspect_ratio")
        if image_aspect_ratio is not None and image_aspect_ratio not in IMAGE_ASPECT_CHOICES:
            hint = "；YAML 中的宽高比请使用引号包裹，例如 \"16:9\"" if not isinstance(image_aspect_ratio, str) else ""
            fail(
                f"第 {index} 个 image task 的 aspect 必须是 {', '.join(IMAGE_ASPECT_CHOICES)}，当前为: {image_aspect_ratio}{hint}"
            )
    elif mode == "audio":
        if not task.get("audio_file"):
            fail(f"第 {index} 个 audio task 缺少 audio_file")
        if task.get("reference"):
            fail(f"第 {index} 个 audio task 不支持 reference")
    elif mode == "video":
        if not task.get("prompt") and not task.get("resume_task_id"):
            fail(f"第 {index} 个 video task 缺少 prompt 或 resume_task_id")
        if task.get("audio_file"):
            fail(f"第 {index} 个 video task 不支持 audio_file")


def get_batch_concurrency(modes, configs, yaml_data):
    raw = yaml_data.get("concurrency")
    if raw is None:
        shared_config = next(iter(configs.values()))
        raw = get_config_value("LLM_CONCURRENCY", shared_config)
    if raw is None:
        raw = "4"
    try:
        value = int(raw)
    except (TypeError, ValueError):
        fail(f"concurrency 必须是整数，当前为: {raw}")
    if value <= 0:
        fail(f"concurrency 必须大于 0，当前为: {value}")
    return value


def resolve_task_output(mode, task, output_dir, yaml_dir):
    output = task.get("output")
    if output:
        output_path = Path(output)
        if output_dir and not output_path.is_absolute():
            output_path = Path(output_dir) / output_path
        elif not output_path.is_absolute():
            output_path = yaml_dir / output_path
        return str(output_path.resolve())

    edit_path = task.get("edit")
    if edit_path:
        edit_target = Path(edit_path)
        if not edit_target.is_absolute():
            edit_target = yaml_dir / edit_target
        return str(edit_target.resolve())

    if mode == "image":
        base_dir = Path(output_dir).resolve() if output_dir else (yaml_dir / "gemini-output").resolve()
        task_id = task.get("id") or f"task_{datetime.now().strftime('%H%M%S_%f')}"
        return str(base_dir / f"{task_id}.jpg")

    if mode == "audio":
        audio_path = resolve_path(task["audio_file"], base_dir=yaml_dir)
        return str(audio_path.with_suffix(".srt"))
    if mode == "video":
        base_dir = Path(output_dir).resolve() if output_dir else (yaml_dir / "gemini-output").resolve()
        task_id = task.get("id") or f"task_{datetime.now().strftime('%H%M%S_%f')}"
        return str(base_dir / f"{task_id}.mp4")

    return None


def run_batch(yaml_path_str: str):
    ensure_yaml_available()

    yaml_path = resolve_path(yaml_path_str)
    if not yaml_path.exists():
        fail(f"YAML 文件不存在: {yaml_path}")

    try:
        with open(yaml_path, encoding="utf-8") as file:
            data = yaml.safe_load(file) or {}
    except FileNotFoundError:
        fail(f"YAML 文件不存在: {yaml_path}")
    except IsADirectoryError:
        fail(f"YAML 路径不是文件: {yaml_path}")
    except UnicodeDecodeError:
        fail(f"YAML 文件不是有效的 UTF-8 文本: {yaml_path}")
    except yaml.YAMLError as exc:
        fail(f"YAML 解析失败: {yaml_path} ({exc})")
    except OSError as exc:
        fail(f"读取 YAML 文件失败: {yaml_path} ({exc})")

    if not isinstance(data, dict):
        fail("YAML 顶层必须是对象")

    yaml_dir = yaml_path.parent
    if "mode" not in data:
        fail("batch YAML 顶层缺少必填字段 mode")
    default_mode = normalize_mode(data.get("mode"), field_name="顶层 mode")
    tasks = data.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        fail("batch 模式要求 tasks 为非空数组")

    output_dir = data.get("output_dir")
    if output_dir:
        output_dir = str(resolve_path(output_dir, base_dir=yaml_dir))
        Path(output_dir).mkdir(parents=True, exist_ok=True)

    global_system_prompt = data.get("system_prompt")
    global_prompt = data.get("prompt")
    global_temperature = data.get("temperature")
    global_max_output_tokens = data.get("max_output_tokens")
    global_input = data.get("input")
    global_reference = data.get("reference")
    global_audio_file = data.get("audio_file")
    global_edit = data.get("edit")
    global_model = data.get("model")

    prepared = []
    modes = set()
    for index, task in enumerate(tasks, 1):
        if not isinstance(task, dict):
            fail(f"第 {index} 个 task 不是对象")
        mode = normalize_mode(task.get("mode", default_mode), field_name=f"第 {index} 个 task 的 mode")
        input_paths = normalize_task_input(task.get("input", global_input), index)
        task_spec = {
            "index": index,
            "id": task.get("id", f"task-{index}"),
            "mode": mode,
            "prompt": task.get("prompt", global_prompt),
            "system_prompt": task.get("system_prompt", global_system_prompt),
            "input_paths": input_paths,
            "reference": task.get("reference", global_reference),
            "audio_file": task.get("audio_file", global_audio_file),
            "edit_path": task.get("edit", global_edit),
            "output": None,
            "temperature": task.get("temperature", global_temperature),
            "max_output_tokens": task.get("max_output_tokens", global_max_output_tokens),
            "model": task.get("model", global_model),
            "count": task.get("count", 1),
            "image_size": task.get("size"),
            "image_aspect_ratio": task.get("aspect"),
            "video_seconds": task.get("seconds"),
            "video_size": task.get("size"),
            "resume_task_id": task.get("resume_task_id"),
            "config": None,
        }
        validate_task_fields(mode, task_spec, index)
        task_spec["output"] = resolve_task_output(mode, task, output_dir, yaml_dir)
        prepared.append(task_spec)
        modes.add(mode)

    clients = {}
    configs = {}
    provider_names = []
    for mode in modes:
        client, model, config = create_client(mode)
        clients[mode] = (client, model)
        configs[mode] = config
        provider_names.append((config.get("provider") or {}).get("name") or get_config_value("BASE_URL", config) or mode)

    for spec in prepared:
        spec["config"] = configs[spec["mode"]]

    concurrency = get_batch_concurrency(modes, configs, data)

    total = len(prepared)
    max_workers = min(total, concurrency)
    print(f"Providers: {', '.join(sorted(set(provider_names)))}")
    print(f"开始执行 {total} 个任务（并发数: {max_workers}）\n")

    def run_one(task_spec):
        task_model = task_spec.get("model")
        if task_model:
            client, model, _ = create_client(task_spec["mode"], explicit_model=task_model)
        else:
            client, model = clients[task_spec["mode"]]

        task_id = task_spec["id"]
        print(f"[{task_id}] 开始 | 模型: {model}")

        def progress(event, **payload):
            if event == "start":
                print(f"[{task_id}] 开始生成 {payload['total']} 张图片（并发数: {payload['concurrency']}）")
            elif event == "progress":
                print(f"[{task_id}] [{payload['completed']}/{payload['total']}] 已完成")

        result = task_spec, run_task(
            task_spec["mode"],
            client,
            model,
            prompt=task_spec["prompt"],
            system_prompt=task_spec["system_prompt"],
            input_paths=task_spec["input_paths"],
            reference=task_spec["reference"],
            audio_file=task_spec["audio_file"],
            output=task_spec["output"],
            temperature=task_spec["temperature"],
            max_output_tokens=task_spec["max_output_tokens"],
            base_dir=yaml_dir,
            edit_path=task_spec["edit_path"],
            image_count=task_spec["count"],
            image_size=task_spec["image_size"],
            image_aspect_ratio=task_spec["image_aspect_ratio"],
            video_seconds=task_spec["video_seconds"],
            video_size=task_spec["video_size"],
            resume_task_id=task_spec["resume_task_id"],
            config=task_spec["config"],
            progress_callback=progress if task_spec["mode"] == "image" and task_spec["count"] > 1 else None,
        )

        print(f"[{task_id}] 完成")
        return result

    success = 0
    failed = 0

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(run_one, spec): spec for spec in prepared}
        for future in as_completed(futures):
            spec = futures[future]
            task_id = spec["id"]
            try:
                _, result = future.result()
                if result["mode"] == "image":
                    print(f"[{task_id}] 已写入图片: {', '.join(result['output_paths'])}")
                elif result["mode"] == "video":
                    print(f"[{task_id}] 已写入视频: {', '.join(result['output_paths'])}")
                elif result.get("output_path"):
                    print(f"[{task_id}] 已写入: {result['output_path']}")
                else:
                    print(f"[{task_id}]")
                    print(result["text"])
                success += 1
            except Exception as exc:
                print(f"[{task_id}] 错误: {exc}", file=sys.stderr)
                failed += 1

    print(f"\n完成！成功 {success}，失败 {failed}")
    if failed:
        sys.exit(1)
