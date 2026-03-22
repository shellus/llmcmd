import click

from . import api
from .batch import run_batch
from .config import create_client
from .interactive import run_interactive_chat
from .messages import DEFAULT_AUDIO_PROMPT
from .session import append_session_messages, load_session_messages, resolve_session_path
from .task import run_task
from .utils import fail, resolve_text


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


def _render_text_result(result):
    if result.get("output_path"):
        print(f"已写入: {result['output_path']}")
    else:
        print(result["text"])


def _stream_to_stdout(chunk):
    click.echo(chunk, nl=False)


def _run_chat_once(
    client,
    resolved_model,
    *,
    prompt,
    input_files,
    reference,
    edit_path,
    system,
    output,
    temperature,
    max_output_tokens,
    session_path=None,
):
    history_messages = load_session_messages(session_path) if session_path else []
    if history_messages and (system or input_files or reference or edit_path):
        fail("持久会话模式暂不支持与 --system/-i/-r/--edit 组合使用")

    task_kwargs = {
        "prompt": prompt,
        "system_prompt": system,
        "input_paths": input_files,
        "reference": reference,
        "output": output,
        "temperature": temperature,
        "max_output_tokens": max_output_tokens,
        "edit_path": edit_path,
    }
    user_message = None
    if session_path:
        if edit_path:
            fail("持久会话模式暂不支持 --edit")
        if reference:
            fail("持久会话模式暂不支持 -r/--reference")
        if input_files:
            fail("持久会话模式暂不支持 -i/--input")
        if system:
            fail("持久会话模式暂不支持 --system")
        prompt_text = resolve_text(prompt)
        if not prompt_text:
            fail("持久会话模式至少需要 prompt")
        user_message = {"role": "user", "content": prompt_text}
        task_kwargs = {
            "messages": [*history_messages, user_message],
            "output": output,
            "temperature": temperature,
            "max_output_tokens": max_output_tokens,
        }

    result = _run_safely(
        run_task,
        "chat",
        client,
        resolved_model,
        **task_kwargs,
    )
    if session_path:
        append_session_messages(session_path, [user_message, {"role": "assistant", "content": result["text"]}])
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
  llm chat "总结重点" -i article.md -i notes.md
  llm chat "详细描述这张图" -r photo.jpg
  llm chat "把人物脸型改成偏瘦" --edit prompt.md
  llm chat "按要求改写" --edit prompt.md -o prompt.v2.md
"""
)
@click.argument("prompt", required=False, default=None, metavar="[PROMPT|@FILE]")
@click.option("-i", "--input", "input_files", multiple=True, help="补充上下文文本文件，可重复传入多个")
@click.option("-r", "--reference", multiple=True, help="参考图片路径（仅图片），用于视觉理解，可重复传入")
@click.option("--edit", "edit_path", default=None, help="编辑目标文本文件；模型将输出 diff 并自动应用")
@click.option("-s", "--session", "session_name", default=None, help="加载/持久化对话历史；可传会话名或 JSONL 路径")
@click.option("--system", default=None, help="system prompt，可使用 @文件路径 从文件读取")
@click.option("-I", "--interactive", is_flag=True, help="进入交互式连续对话，并默认持久化到当前路径")
@click.option("-o", "--output", default=None, help="输出路径；edit 模式下不传则直接覆盖原文件")
@click.option("--model", default=None, help="覆盖当前 mode 的模型")
@click.option("-t", "--temperature", type=float, default=None, help="高级选项：采样温度")
@click.option("-m", "--max-output-tokens", type=int, default=None, help="高级选项：最大输出 token 数")
@click.option("--debug", is_flag=True, hidden=True, is_eager=True, expose_value=False, callback=_set_debug)
def chat(prompt, input_files, reference, edit_path, session_name, system, interactive, output, model, temperature, max_output_tokens):
    """对话/文本生成。

    PROMPT 支持直接传字面量，也支持使用 @文件路径 从文件读取。
    可配合 -i 补充文本文件上下文，配合 -r 传入图片进行视觉理解。
    指定 --edit 时进入文件编辑模式：模型输出 diff，CLI 自动应用；不传 -o 时直接覆盖原文件。
    """
    if edit_path and not prompt:
        fail("chat edit 模式需要提供修改要求 prompt")
    if interactive and output:
        fail("交互式对话不支持 --output")
    client, resolved_model, _ = create_client("chat", explicit_model=model)
    session_path = resolve_session_path(session_name, interactive=interactive) if (interactive or session_name is not None) else None
    if interactive:
        run_interactive_chat(
            client=client,
            model=resolved_model,
            prompt=prompt,
            session_path=session_path,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            history_messages=load_session_messages(session_path),
        )
        return

    result = _run_chat_once(
        client,
        resolved_model,
        prompt=prompt,
        input_files=input_files,
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
  llm image @prompt.txt -i constraints.md -r ref.jpg -o result.jpg
  llm image "生成海报" -o poster.jpg
  llm image "生成三张海报方案" -n 3 -o poster.jpg
"""
)
@click.argument("prompt", metavar="PROMPT|@FILE")
@click.option("-i", "--input", "input_files", multiple=True, help="补充上下文文本文件，可重复传入多个")
@click.option("-r", "--reference", multiple=True, help="参考图片路径（仅图片），可重复传入")
@click.option("-s", "--system", default=None, help="system prompt，可使用 @文件路径 从文件读取")
@click.option("-o", "--output", default=None, help="输出路径")
@click.option("-n", "--count", type=int, default=1, show_default=True, help="生成数量；会遵循 image 模式并发配置")
@click.option("--model", default=None, help="覆盖当前 mode 的模型")
@click.option("-t", "--temperature", type=float, default=None, help="高级选项：采样温度")
@click.option("-m", "--max-output-tokens", type=int, default=None, help="高级选项：最大输出 token 数")
@click.option("--debug", is_flag=True, hidden=True, is_eager=True, expose_value=False, callback=_set_debug)
def image(prompt, input_files, reference, system, output, count, model, temperature, max_output_tokens):
    """图片生成或参考图编辑。

    PROMPT 为必填，支持直接传字面量，也支持使用 @文件路径 从文件读取。
    可选 -i 传入补充文本约束文件，可选 -r 传入参考图（仅图片），进行参考图编辑或风格迁移。
    通过 -n/--count 指定生成数量，单次多图会遵循 image 模式并发配置。
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
        input_paths=input_files,
        reference=reference,
        output=output,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        image_count=count,
        config=config,
        progress_callback=_image_progress if count > 1 else None,
    )
    print("已写入图片:", ", ".join(result["output_paths"]))


@cli.command(
    epilog="""\b
使用示例:
  llm audio demo.m4a
  llm audio demo.m4a -p "转成逐字稿"
  llm audio demo.m4a -o demo.srt
"""
)
@click.argument("audio_file", metavar="AUDIO_FILE")
@click.option("-p", "--prompt", default=None, help="prompt 文本，或使用 @文件路径 从文件读取")
@click.option("-s", "--system", default=None, help="system prompt，可使用 @文件路径 从文件读取")
@click.option("-o", "--output", default=None, help="输出路径")
@click.option("--model", default=None, help="覆盖当前 mode 的模型")
@click.option("-t", "--temperature", type=float, default=None, help="高级选项：采样温度")
@click.option("-m", "--max-output-tokens", type=int, default=None, help="高级选项：最大输出 token 数")
@click.option("--debug", is_flag=True, hidden=True, is_eager=True, expose_value=False, callback=_set_debug)
def audio(audio_file, prompt, system, output, model, temperature, max_output_tokens):
    """音频转录为文本或 SRT。

    AUDIO_FILE 为必填音频文件路径。
    额外要求通过 -p/--prompt 指定，支持字面量或 @文件路径。
    """
    prompt = prompt or DEFAULT_AUDIO_PROMPT
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
    )
    print(f"已写入: {result['output_path']}")


@cli.command(
    epilog="""\b
使用示例:
  llm batch tasks.yaml
"""
)
@click.argument("yaml_path", metavar="YAML_PATH")
@click.option("--debug", is_flag=True, hidden=True, is_eager=True, expose_value=False, callback=_set_debug)
def batch(yaml_path):
    """YAML 批量执行。

    读取批处理配置并并发执行多个任务。
    YAML 中支持 mode: chat / image / audio，chat 模式支持 reference 图片输入。
    """
    _run_safely(run_batch, yaml_path)


if __name__ == "__main__":
    cli()
