import asyncio
from pathlib import Path
from time import perf_counter

import click
from prompt_toolkit.document import Document

from .session import append_session_messages
from .task import run_task


def _session_display_name(session_path):
    path = Path(session_path)
    return path.stem if path.suffix == ".jsonl" else path.name


class _TranscriptLexer:
    ROLE_PREFIXES = {
        "你  ": ("class:role.user", "class:message.user"),
        "AI  ": ("class:role.assistant", "class:message.assistant"),
        "系统": ("class:role.system", "class:message.system"),
    }

    def lex_document(self, document):
        def get_line(lineno):
            line = document.lines[lineno]
            for prefix, styles in self.ROLE_PREFIXES.items():
                if line.startswith(prefix):
                    role_style, message_style = styles
                    return [(role_style, prefix), (message_style, line[len(prefix) :])]
            return [("", line)]

        return get_line


class InteractiveChatState:
    ROLE_STYLES = {
        "user": ("你  ", "class:role.user", "class:message.user"),
        "assistant": ("AI  ", "class:role.assistant", "class:message.assistant"),
        "system": ("系统", "class:role.system", "class:message.system"),
    }

    def __init__(self, *, model, session_path, history_messages):
        self.model = model
        self.session_path = Path(session_path)
        self.message_count = len(history_messages)
        self.status = "已就绪"
        self.phase = "空闲"
        self.metric_label = "上轮耗时"
        self.metric_value = "-"
        self.transcript_entries = []
        self._assistant_open = False
        self._assistant_entry = None
        self._response_started_at = None
        self._restore_started_at = None
        for message in history_messages:
            self.append_message(message.get("role"), message.get("content", ""))

    @property
    def transcript_text(self):
        return "".join(self._entry_text(entry) for entry in self.transcript_entries)

    def transcript_fragments(self):
        fragments = []
        for entry in self.transcript_entries:
            label, role_style, message_style = self.ROLE_STYLES[entry["role"]]
            fragments.append((role_style, label))
            fragments.append((message_style, entry["text"]))
            fragments.append(("", "\n"))
        return fragments

    def status_fragments(self):
        return [
            ("class:status.bracket", "["),
            ("class:status.label", "状态: "),
            ("class:status.value", self.status),
            ("class:status.sep", " | "),
            ("class:status.label", f"{self.metric_label}: "),
            ("class:status.value", self.metric_value),
            ("class:status.sep", " | "),
            ("class:status.label", "阶段: "),
            ("class:status.value", self.phase),
            ("class:status.bracket", "]"),
        ]

    def toolbar_fragments(self):
        return [
            ("class:toolbar.sep", "─"),
            ("class:toolbar.label", " 模型: "),
            ("class:toolbar.value", str(self.model)),
            ("class:toolbar.sep", " | "),
            ("class:toolbar.label", "消息: "),
            ("class:toolbar.value", str(self.message_count)),
            ("class:toolbar.sep", " | "),
            ("class:toolbar.label", "会话: "),
            ("class:toolbar.value", _session_display_name(self.session_path)),
            ("class:toolbar.sep", " ─"),
        ]

    def append_message(self, role, content):
        if role not in self.ROLE_STYLES:
            return
        text = self._normalize_content(content)
        if not text:
            return
        self.transcript_entries.append({"role": role, "text": text})

    def begin_restore(self):
        self.status = "恢复中"
        self.phase = "回放历史"
        self.metric_label = "已耗时"
        self.metric_value = "0.00s"
        self._restore_started_at = perf_counter()

    def finish_restore(self):
        self.status = "已就绪"
        self.phase = "恢复完成"
        self.metric_label = "恢复耗时"
        self.metric_value = self._elapsed_since(self._restore_started_at)
        self._restore_started_at = None

    def begin_assistant_response(self):
        self.status = "等待首字"
        self.phase = "已发出请求"
        self.metric_label = "本轮耗时"
        self.metric_value = "0.00s"
        self._assistant_open = False
        self._assistant_entry = None
        self._response_started_at = perf_counter()

    def write_assistant_chunk(self, chunk):
        if not chunk:
            return
        self._refresh_active_elapsed()
        if not self._assistant_open:
            self.transcript_entries.append({"role": "assistant", "text": ""})
            self._assistant_entry = self.transcript_entries[-1]
            self._assistant_open = True
            self.status = "回复中"
            self.phase = "流式输出"
        self._assistant_entry["text"] += chunk

    def finish_assistant_response(self):
        self._refresh_active_elapsed()
        self._assistant_open = False
        self._assistant_entry = None
        self.status = "已就绪"
        self.phase = "回复完成"
        self.metric_label = "上轮耗时"
        self._response_started_at = None

    def mark_error(self):
        self._refresh_active_elapsed()
        self.status = "出错"
        self.phase = "请求失败"
        self.metric_label = "本轮耗时"
        self._assistant_open = False
        self._assistant_entry = None
        self._response_started_at = None

    def complete_round(self, user_text, assistant_text):
        self.append_message("user", user_text)
        self.message_count += 1
        self.begin_assistant_response()
        self.write_assistant_chunk(assistant_text)
        self.finish_assistant_response()
        self.message_count += 1

    def _refresh_active_elapsed(self):
        if self._response_started_at is not None:
            self.metric_value = self._elapsed_since(self._response_started_at)
        elif self._restore_started_at is not None:
            self.metric_value = self._elapsed_since(self._restore_started_at)

    @staticmethod
    def _entry_text(entry):
        label, _, _ = InteractiveChatState.ROLE_STYLES[entry["role"]]
        return f"{label}{entry['text']}\n"

    @staticmethod
    def _elapsed_since(started_at):
        if started_at is None:
            return "-"
        return f"{max(perf_counter() - started_at, 0):.2f}s"

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
        lexer=_TranscriptLexer(),
    )
    status_line = Window(height=1, content=FormattedTextControl(state.status_fragments))
    input_area = TextArea(
        text="",
        multiline=False,
        wrap_lines=False,
        prompt="你> ",
    )
    toolbar_line = Window(height=1, content=FormattedTextControl(state.toolbar_fragments))

    def accept(buff):
        text = buff.text.strip()
        if not text:
            buff.text = ""
            return False
        buff.text = ""
        on_submit(text)
        return False

    input_area.buffer.accept_handler = accept

    kb = KeyBindings()

    @kb.add("c-c")
    def _exit(event):
        event.app.exit()

    style = Style.from_dict(
        {
            "prompt": "#60a5fa",
            "status.bracket": "#4b5563",
            "status.label": "#94a3b8",
            "status.value": "#e5e7eb",
            "status.sep": "#475569",
            "toolbar.label": "#64748b",
            "toolbar.value": "#cbd5e1",
            "toolbar.sep": "#334155",
            "role.user": "#60a5fa bold",
            "role.assistant": "#34d399 bold",
            "role.system": "#fbbf24 bold",
            "message.user": "",
            "message.assistant": "",
            "message.system": "#d1d5db",
        }
    )

    root = HSplit([output_area, status_line, input_area, toolbar_line])

    return Application(layout=Layout(root, focused_element=input_area), key_bindings=kb, full_screen=False, style=style), output_area


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
    state = InteractiveChatState(model=model, session_path=session_path, history_messages=[])
    state.begin_restore()
    for message in history_messages:
        state.append_message(message.get("role"), message.get("content", ""))
    state.finish_restore()
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

        try:
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
        except Exception:
            state.mark_error()
            sync_output(output_area)
            app_ref["busy"] = False
            raise

        if not assistant_parts and result["text"]:
            state.write_assistant_chunk(result["text"])
        state.finish_assistant_response()
        state.message_count += 1
        assistant_text = result["text"]
        append_session_messages(session_path, [{"role": "user", "content": user_text}, {"role": "assistant", "content": assistant_text}])
        history_messages.extend([{"role": "user", "content": user_text}, {"role": "assistant", "content": assistant_text}])
        sync_output(output_area)
        app_ref["busy"] = False

    def submit(user_text, output_area):
        if app_ref["busy"]:
            return
        app_ref["busy"] = True
        app_ref["app"].create_background_task(process_submission(user_text, output_area))

    app, output_area = _create_application(state, on_submit=lambda user_text: submit(user_text, output_area))
    app_ref["app"] = app

    def pre_run():
        sync_output(output_area)
        if prompt:
            submit(prompt, output_area)

    app.run(pre_run=pre_run)
