from pathlib import Path
import asyncio

import click
from prompt_toolkit.document import Document

from .session import append_session_messages
from .task import run_task


def _session_display_name(session_path):
    path = Path(session_path)
    return path.stem if path.suffix == ".jsonl" else path.name


class InteractiveChatState:
    def __init__(self, *, model, session_path, history_messages):
        self.model = model
        self.session_path = Path(session_path)
        self.message_count = len(history_messages)
        self.status = "空闲"
        self.transcript_lines = []
        self._assistant_open = False
        for message in history_messages:
            self.append_message(message.get("role"), message.get("content", ""))

    @property
    def transcript_text(self):
        return "".join(self.transcript_lines)

    def toolbar_fragments(self):
        return [
            ("class:toolbar.label", "模型: "),
            ("class:toolbar.value", str(self.model)),
            ("class:toolbar.sep", " | "),
            ("class:toolbar.label", "消息: "),
            ("class:toolbar.value", str(self.message_count)),
            ("class:toolbar.sep", " | "),
            ("class:toolbar.label", "会话: "),
            ("class:toolbar.value", _session_display_name(self.session_path)),
            ("class:toolbar.sep", " | "),
            ("class:toolbar.label", "状态: "),
            ("class:toolbar.status", self.status),
        ]

    def append_message(self, role, content):
        if role == "user":
            prefix = "你> "
        elif role == "assistant":
            prefix = "AI> "
        elif role == "system":
            prefix = "系统> "
        else:
            return
        text = self._normalize_content(content)
        if not text:
            return
        self.transcript_lines.append(f"{prefix}{text}\n")

    def begin_assistant_response(self):
        self.status = "等待首字"
        self._assistant_open = False

    def write_assistant_chunk(self, chunk):
        if not chunk:
            return
        if not self._assistant_open:
            self.transcript_lines.append("AI> ")
            self._assistant_open = True
            self.status = "输出中"
        self.transcript_lines.append(chunk)

    def finish_assistant_response(self):
        if self._assistant_open:
            self.transcript_lines.append("\n")
        self._assistant_open = False
        self.status = "空闲"

    def complete_round(self, user_text, assistant_text):
        self.append_message("user", user_text)
        self.message_count += 1
        self.begin_assistant_response()
        self.write_assistant_chunk(assistant_text)
        self.finish_assistant_response()
        self.message_count += 1

    @staticmethod
    def _normalize_content(content):
        if isinstance(content, list):
            return "\n".join(str(item) for item in content).strip()
        return str(content).strip()


def _create_application(state, *, on_submit):
    try:
        from prompt_toolkit import Application
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout import HSplit, Layout, Window
        from prompt_toolkit.layout.controls import FormattedTextControl
        from prompt_toolkit.styles import Style
        from prompt_toolkit.widgets import TextArea
    except ImportError as exc:
        raise click.ClickException("交互式对话需要安装 prompt_toolkit") from exc

    output_area = TextArea(
        text=state.transcript_text,
        read_only=True,
        scrollbar=True,
        focusable=False,
        wrap_lines=True,
    )
    input_area = TextArea(
        text="",
        multiline=False,
        wrap_lines=False,
        prompt="你> ",
    )

    def accept(buff):
        text = buff.text.strip()
        if not text:
            buff.text = ""
            return False
        buff.text = ""
        on_submit(text, output_area)
        return False

    input_area.buffer.accept_handler = accept

    kb = KeyBindings()

    @kb.add("c-c")
    def _exit(event):
        event.app.exit()

    style = Style.from_dict(
        {
            "output": "",
            "input": "",
            "prompt": "#93c5fd",
            "bottom-toolbar": "bg:#1f2937 #e5e7eb",
            "toolbar.label": "bg:#1f2937 #93c5fd",
            "toolbar.value": "bg:#1f2937 #f9fafb",
            "toolbar.sep": "bg:#1f2937 #6b7280",
            "toolbar.status": "bg:#1f2937 #fbbf24",
        }
    )

    root = HSplit(
        [
            output_area,
            input_area,
            Window(height=1, content=FormattedTextControl(state.toolbar_fragments), style="class:bottom-toolbar"),
        ]
    )

    return Application(layout=Layout(root, focused_element=input_area), key_bindings=kb, full_screen=False, style=style), output_area, input_area


def run_interactive_chat(
    *,
    client,
    model,
    prompt,
    session_path,
    temperature,
    max_output_tokens,
    history_messages,
):
    state = InteractiveChatState(model=model, session_path=session_path, history_messages=history_messages)
    click.echo(f"会话: {session_path} | 已加载 {len(history_messages)} 条消息")

    app_ref = {"busy": False}

    def sync_output(output_area):
        output_area.buffer.set_document(Document(text=state.transcript_text, cursor_position=len(state.transcript_text)), bypass_readonly=True)
        app = app_ref.get("app")
        if app is not None:
            app.invalidate()

    async def process_submission(user_text, output_area):
        state.append_message("user", user_text)
        state.message_count += 1
        sync_output(output_area)

        assistant_parts = []
        state.begin_assistant_response()
        sync_output(output_area)

        def handle_chunk(chunk):
            assistant_parts.append(chunk)
            state.write_assistant_chunk(chunk)
            sync_output(output_area)

        result = await asyncio.to_thread(
            run_task,
            "chat",
            client,
            model,
            messages=[*history_messages, {"role": "user", "content": user_text}],
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            stream_handler=handle_chunk,
        )

        state.finish_assistant_response()
        state.message_count += 1
        assistant_text = result["text"] if assistant_parts else result["text"]
        append_session_messages(session_path, [{"role": "user", "content": user_text}, {"role": "assistant", "content": assistant_text}])
        history_messages.extend([{"role": "user", "content": user_text}, {"role": "assistant", "content": assistant_text}])
        sync_output(output_area)
        app_ref["busy"] = False

    def submit(user_text, output_area):
        if app_ref["busy"]:
            return
        app_ref["busy"] = True
        app_ref["app"].create_background_task(process_submission(user_text, output_area))

    app, output_area, input_area = _create_application(state, on_submit=submit)
    app_ref["app"] = app

    def pre_run():
        sync_output(output_area)
        if prompt:
            submit(prompt, output_area)

    app.run(pre_run=pre_run)
