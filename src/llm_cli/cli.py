import sys
from datetime import datetime, timezone
from time import perf_counter

import click

from . import api
from .batch import run_batch
from .config import create_client
from .interactive import run_interactive_chat
from .session import append_session_messages, load_session_messages, replace_leading_system_messages, resolve_session_path, rewrite_session_messages
from .task import run_task
from .utils import IMAGE_ASPECT_CHOICES, IMAGE_SIZE_CHOICES, fail, resolve_text


def _now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _set_debug(ctx, param, value):
    """eager callback，设置 DEBUG 标志"""
    if value:
        api.set_debug(True)


def _run_safely(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except SystemExit:
        raise
    except click.ClickException:
        raise
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


def _image_progress(event, **payload):
    if event == "start":
        print(f"开始生成 {payload['total']} 张图片（并发数: {payload['concurrency']}）")
    elif event == "progress":
        print(f"[{payload['completed']}/{payload['total']}] 已完成")


def _video_progress(event, **payload):
    if event == "task_created":
        print(f"任务 ID: {payload['task_id']}")
    elif event == "poll" and api.DEBUG:
        progress = payload.get("progress")
        waited_seconds = payload.get("waited_seconds")
        next_delay_seconds = payload.get("next_delay_seconds")
        suffix = f", progress={progress}" if progress is not None else ""
        if waited_seconds is not None:
            suffix += f", waited={waited_seconds}s"
        if next_delay_seconds is not None:
            suffix += f", next_poll={next_delay_seconds}s"
        click.echo(f"[DEBUG] 视频状态: task_id={payload['task_id']}, status={payload.get('status')}{suffix}", err=True)
    elif event == "task_completed" and api.DEBUG:
        click.echo(f"[DEBUG] 视频完成: task_id={payload['task_id']}, status={payload.get('status')}", err=True)
    elif event == "download_start" and api.DEBUG:
        click.echo(f"[DEBUG] 开始下载视频: task_id={payload['task_id']}, path={payload['path']}", err=True)
    elif event == "download_progress" and api.DEBUG:
        click.echo(f"[DEBUG] 视频下载进度: task_id={payload['task_id']}, bytes={payload['bytes_written']}", err=True)
    elif event == "download_done" and api.DEBUG:
        click.echo(
            f"[DEBUG] 视频下载完成: task_id={payload['task_id']}, bytes={payload['bytes_written']}, path={payload['path']}",
            err=True,
        )


def _render_text_result(result):
    if result.get("output_paths"):
        print("已写入图片:", ", ".join(result["output_paths"]))
    elif result.get("output_path"):
        print(f"已写入: {result['output_path']}")
    elif result.get("already_streamed"):
        click.echo()
    else:
        print(result["text"])


def _stream_to_stdout(chunk):
    sys.stdout.write(chunk)
    sys.stdout.flush()


def _request_messages(messages):
    return [{"role": message["role"], "content": message.get("content", "")} for message in messages]


def _run_chat_once(
    client,
    resolved_model,
    *,
    prompt,
    reference,
    edit_path,
    system,
    output,
    temperature,
    max_output_tokens,
    session_path=None,
):
    history_messages = load_session_messages(session_path) if session_path else []
    if history_messages and (reference or edit_path):
        fail("持久会话模式暂不支持与 --system/-r/--edit 组合使用")

    task_kwargs = {
        "prompt": prompt,
        "system_prompt": system,
        "reference": reference,
        "output": output,
        "temperature": temperature,
        "max_output_tokens": max_output_tokens,
        "edit_path": edit_path,
    }
    should_stream_output = output is None
    user_message = None
    if session_path:
        if edit_path:
            fail("持久会话模式暂不支持 --edit")
        if reference:
            fail("持久会话模式暂不支持 -r/--reference")
        history_messages = replace_leading_system_messages(history_messages, resolve_text(system) if system else None)
        if system:
            rewrite_session_messages(session_path, history_messages)
        prompt_text = resolve_text(prompt)
        if not prompt_text:
            fail("持久会话模式至少需要 prompt")
        started_at = _now_iso()
        started_counter = perf_counter()
        user_message = {"role": "user", "content": prompt_text, "meta": {"started_at": started_at}}
        task_kwargs = {
            "messages": _request_messages([*history_messages, user_message]),
            "output": output,
            "temperature": temperature,
            "max_output_tokens": max_output_tokens,
        }

    result = _run_safely(
        run_task,
        "chat",
        client,
        resolved_model,
        stream_handler=_stream_to_stdout if should_stream_output else None,
        **task_kwargs,
    )
    if should_stream_output and not result.get("output_paths") and result.get("text"):
        result["already_streamed"] = True
    if session_path:
        elapsed_seconds = round(max(perf_counter() - started_counter, 0), 2)
        append_session_messages(
            session_path,
            [
                user_message,
                {
                    "role": "assistant",
                    "content": result["text"],
                    "meta": {"finished_at": _now_iso(), "elapsed_seconds": elapsed_seconds},
                },
            ],
        )
    return result


@click.group(context_settings=dict(help_option_names=["-h", "--help"]))
@click.option("--debug", is_flag=True, is_eager=True, expose_value=False, callback=_set_debug, help="输出详细的请求响应信息")
def cli():
    """统一 LLM CLI：chat / image / audio / batch。"""
    pass


@cli.command(name="chat",
    epilog="""\b
使用示例:
  llm chat "写一段产品介绍"
  llm chat @prompt.txt -o result.md
  llm chat "总结重点" -r article.pdf -r notes.txt
  llm chat "详细描述这张图" -r photo.jpg
  llm chat "把人物脸型改成偏瘦" --edit prompt.md
  llm chat "按要求改写" --edit prompt.md -o prompt.v2.md
"""
)
@click.argument("prompt", required=False, default=None, metavar="[PROMPT|@FILE]")
@click.option("-r", "--reference", multiple=True, help="上传附件，可重复传入多个")
@click.option("--edit", "edit_path", default=None, help="编辑目标文本文件；模型将输出 diff 并自动应用")
@click.option("-s", "--session", "session_name", default=None, help="加载/持久化对话历史；可传会话名或 JSONL 路径")
@click.option("--system", default=None, help="system prompt，可使用 @文件路径 从文件读取")
@click.option("-I", "--interactive", is_flag=True, help="进入交互式连续对话；仅在配合 -s 时持久化")
@click.option("-o", "--output", default=None, help="输出路径；edit 模式下不传则直接覆盖原文件")
@click.option("--model", default=None, help="覆盖当前 mode 的模型")
@click.option("-t", "--temperature", type=float, default=None, help="高级选项：采样温度")
@click.option("-m", "--max-output-tokens", type=int, default=None, help="高级选项：最大输出 token 数")
@click.option("--probe-input", is_flag=True, hidden=True, help="调试交互式输入事件")
@click.option("--debug", is_flag=True, is_eager=True, expose_value=False, callback=_set_debug, help="输出详细的请求响应信息")
def chat(prompt, reference, edit_path, session_name, system, interactive, output, model, temperature, max_output_tokens, probe_input):
    """对话/文本生成。

    PROMPT 支持直接传字面量，也支持使用 @文件路径 从文件读取。
    可配合 -r 上传附件与模型对话；文本文件若要直接并入 prompt，请使用 @文件路径。
    指定 --edit 时进入文件编辑模式：模型输出 diff，CLI 自动应用；不传 -o 时直接覆盖原文件。
    """
    if edit_path and not prompt:
        fail("chat edit 模式需要提供修改要求 prompt")
    if interactive and output:
        fail("交互式对话不支持 --output")
    client, resolved_model, _ = create_client("chat", explicit_model=model)
    session_path = resolve_session_path(session_name, interactive=interactive) if session_name is not None else None
    if interactive:
        run_interactive_chat(
            client=client,
            model=resolved_model,
            prompt=prompt,
            session_path=session_path,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            history_messages=load_session_messages(session_path) if session_path else [],
            system_prompt=system,
            probe_input=probe_input,
        )
        return

    result = _run_chat_once(
        client,
        resolved_model,
        prompt=prompt,
        reference=reference,
        edit_path=edit_path,
        system=system,
        output=output,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        session_path=session_path,
    )
    _render_text_result(result)


@cli.command(
    epilog="""\b
使用示例:
  llm image "画一只赛博朋克风格的猫"
  llm image "把这张图变成水彩风" -r ref.jpg
  llm image @prompt.txt -r ref.jpg -r style.pdf -o result.jpg
  llm image "生成海报" -o poster.jpg
  llm image "生成三张海报方案" -n 3 -o poster.jpg
  llm image "生成横版海报" --size 2K --aspect 16:9 -o poster.jpg
"""
)
@click.argument("prompt", metavar="PROMPT|@FILE")
@click.option("-r", "--reference", multiple=True, help="上传附件，可重复传入多个")
@click.option("-s", "--system", default=None, help="system prompt，可使用 @文件路径 从文件读取")
@click.option("-o", "--output", default=None, help="输出路径")
@click.option("-n", "--count", type=int, default=1, show_default=True, help="生成数量；会遵循 image 模式并发配置")
@click.option("--size", "image_size", type=click.Choice(IMAGE_SIZE_CHOICES), default=None, help="图片分辨率档位：512 / 1K / 2K / 4K")
@click.option("--aspect", "image_aspect_ratio", type=click.Choice(IMAGE_ASPECT_CHOICES), default=None, help="图片宽高比，例如 1:1 / 16:9 / 9:16")
@click.option("--model", default=None, help="覆盖当前 mode 的模型")
@click.option("-t", "--temperature", type=float, default=None, help="高级选项：采样温度")
@click.option("-m", "--max-output-tokens", type=int, default=None, help="高级选项：最大输出 token 数")
@click.option("--debug", is_flag=True, is_eager=True, expose_value=False, callback=_set_debug, help="输出详细的请求响应信息")
def image(prompt, reference, system, output, count, image_size, image_aspect_ratio, model, temperature, max_output_tokens):
    """图片生成或参考图编辑。

    PROMPT 为必填，支持直接传字面量，也支持使用 @文件路径 从文件读取。
    可选 -r 上传一个或多个附件，作为生成或编辑时的参考输入。
    通过 -n/--count 指定生成数量，单次多图会遵循 image 模式并发配置。
    通过 --size / --aspect 指定分辨率档位与宽高比；会透传给兼容 Gemini 的后端。
    """
    if not prompt:
        fail("image 子命令需要 prompt")
    if count <= 0:
        fail("image 子命令的 count 必须大于 0")
    client, resolved_model, config = create_client("image", explicit_model=model)
    result = _run_safely(
        run_task,
        "image",
        client,
        resolved_model,
        prompt=prompt,
        system_prompt=system,
        reference=reference,
        output=output,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        image_count=count,
        image_size=image_size,
        image_aspect_ratio=image_aspect_ratio,
        config=config,
        progress_callback=_image_progress if count > 1 else None,
    )
    print("已写入图片:", ", ".join(result["output_paths"]))


@cli.command(
    epilog="""\b
使用示例:
  llm video "生成一段海边航拍视频"
  llm video "生成产品展示短片" -r first-frame.jpg --seconds 8 --size 720x1280 -o demo.mp4
  llm video --resume vid_123 -o demo.mp4
"""
)
@click.argument("prompt", required=False, default=None, metavar="[PROMPT|@FILE]")
@click.option("-r", "--reference", multiple=True, help="上传首帧参考图；当前仅使用第一张")
@click.option("-s", "--system", default=None, help="预留参数；当前 video 模式暂不使用 system prompt")
@click.option("-o", "--output", default=None, help="输出路径")
@click.option("--seconds", default=None, help="视频时长秒数；仅在显式传入时透传给上游")
@click.option("--size", "video_size", default=None, help="视频分辨率；仅在显式传入时透传给上游")
@click.option("--resume", "resume_task_id", default=None, help="跳过创建，按任务 ID 恢复等待并下载")
@click.option("--model", default=None, help="覆盖当前 mode 的模型")
@click.option("-t", "--temperature", type=float, default=None, help="预留参数；当前 video 模式暂不使用")
@click.option("-m", "--max-output-tokens", type=int, default=None, help="预留参数；当前 video 模式暂不使用")
@click.option("--debug", is_flag=True, is_eager=True, expose_value=False, callback=_set_debug, help="输出详细的请求响应信息")
def video(prompt, reference, system, output, seconds, video_size, resume_task_id, model, temperature, max_output_tokens):
    """异步视频生成，默认等待完成并自动下载。"""
    if system:
        fail("video 子命令当前暂不支持 --system")
    if resume_task_id and prompt:
        fail("video 子命令使用 --resume 时不能再传 prompt")
    if resume_task_id and reference:
        fail("video 子命令使用 --resume 时不能再传 -r/--reference")
    if not resume_task_id and not prompt:
        fail("video 子命令需要 prompt，或使用 --resume")
    client, resolved_model, config = create_client("video", explicit_model=model)
    result = _run_safely(
        run_task,
        "video",
        client,
        resolved_model,
        prompt=prompt,
        reference=reference,
        output=output,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        video_seconds=seconds,
        video_size=video_size,
        resume_task_id=resume_task_id,
        config=config,
        progress_callback=_video_progress,
    )
    if not resume_task_id and result.get("task_id"):
        print(f"任务已完成: {result['task_id']}")
    print("已写入视频:", ", ".join(result["output_paths"]))


@cli.command(
    epilog="""\b
使用示例:
  llm audio "总结录音内容" -r demo.m4a
  llm audio -r demo.m4a
  llm audio "请输出标准 SRT 字幕" -r demo.m4a -o demo.srt
"""
)
@click.argument("prompt", required=False, default=None, metavar="[PROMPT|@FILE]")
@click.option("-r", "--reference", "audio_file", required=True, help="音频文件路径")
@click.option("-s", "--system", default=None, help="system prompt，可使用 @文件路径 从文件读取")
@click.option("-o", "--output", default=None, help="输出路径")
@click.option("--model", default=None, help="覆盖当前 mode 的模型")
@click.option("-t", "--temperature", type=float, default=None, help="高级选项：采样温度")
@click.option("-m", "--max-output-tokens", type=int, default=None, help="高级选项：最大输出 token 数")
@click.option("--debug", is_flag=True, is_eager=True, expose_value=False, callback=_set_debug, help="输出详细的请求响应信息")
def audio(prompt, audio_file, system, output, model, temperature, max_output_tokens):
    """音频转录为文本或 SRT。

    PROMPT 支持直接传字面量，也支持使用 @文件路径 从文件读取。
    音频文件通过 -r/--reference 传入。
    """
    client, resolved_model, _ = create_client("audio", explicit_model=model)
    result = _run_safely(
        run_task,
        "audio",
        client,
        resolved_model,
        prompt=prompt,
        system_prompt=system,
        audio_file=audio_file,
        output=output,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        stream_handler=_stream_to_stdout,
    )
    if result.get("text"):
        result["already_streamed"] = True
    if output:
        click.echo()
        print(f"已写入: {result['output_path']}")
    elif not result.get("already_streamed"):
        _render_text_result(result)


@cli.command(
    epilog="""\b
使用示例:
  llm batch tasks.yaml
"""
)
@click.argument("yaml_path", metavar="YAML_PATH")
@click.option("--debug", is_flag=True, is_eager=True, expose_value=False, callback=_set_debug, help="输出详细的请求响应信息")
def batch(yaml_path):
    """YAML 批量执行。

    读取批处理配置并并发执行多个任务。
    YAML 中支持 mode: chat / image / audio / video，chat 模式支持 reference 图片输入。
    """
    _run_safely(run_batch, yaml_path)


if __name__ == "__main__":
    cli()
