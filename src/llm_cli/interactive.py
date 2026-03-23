import asyncio
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

import click
from rich.text import Text

from .session import append_session_messages
from .task import run_task


def _session_display_name(session_path):
    path = Path(session_path)
    return path.stem if path.suffix == ".jsonl" else path.name


def _request_messages(messages):
    return [{"role": message["role"], "content": message.get("content", "")} for message in messages]


class InteractiveChatState:
    STATUS_TOKENS = {
        "已就绪": ("○", "idle", "class:status.idle"),
        "恢复中": ("↻", "load", "class:status.load"),
        "等待回复": ("↻", "wait", "class:status.wait"),
        "接收回复": ("⇣", "wait", "class:status.wait"),
        "出错": ("!", "fail", "class:status.fail"),
    }
    ROLE_STYLES = {
        "user": ("你  ", "class:role.user", "class:message.user"),
        "assistant": ("AI  ", "class:role.assistant", "class:message.assistant"),
        "system": ("系统", "class:role.system", "class:message.system"),
    }
    RICH_STYLES = {
        "class:role.user": "bold #60a5fa",
        "class:role.assistant": "bold #34d399",
        "class:role.system": "bold #fbbf24",
        "class:message.user": "",
        "class:message.assistant": "",
        "class:message.system": "#d1d5db",
        "class:assistant.separator": "#334155",
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
        self._response_started_iso = None
        self._restore_started_at = None
        self.user_inputs = []
        self._history_index = None
        self._history_draft = ""
        self.debug_event = None
        for message in history_messages:
            self.append_message(message.get("role"), message.get("content", ""), meta=message.get("meta"))

    @property
    def transcript_text(self):
        return "".join(self._entry_text(entry) for entry in self.transcript_entries)

    def transcript_lines(self):
        lines = []
        for entry in self.transcript_entries:
            label, role_style, message_style = self.ROLE_STYLES[entry["role"]]
            text_lines = entry["text"].splitlines() or [""]
            for index, text_line in enumerate(text_lines):
                if index == 0:
                    lines.append([(role_style, label), (message_style, text_line)])
                else:
                    lines.append([("", " " * len(label)), (message_style, text_line)])
            if entry["role"] == "assistant":
                lines.append([("class:assistant.separator", self._assistant_separator_text(entry))])
        return lines or [[("", "")]]

    def transcript_rich_lines(self):
        rich_lines = []
        for fragments in self.transcript_lines():
            line = Text()
            for style_name, fragment in fragments:
                line.append(fragment, style=self.RICH_STYLES.get(style_name, ""))
            rich_lines.append(line)
        return rich_lines

    def status_fragments(self):
        self._refresh_active_elapsed()
        if self.debug_event:
            return [
                ("class:status.prefix", "·· "),
                ("class:status.fail", "ev"),
                ("", "  "),
                ("class:status.time", self.debug_event),
            ]
        symbol, label, token_style = self._status_token()
        fragments = [
            ("class:status.prefix", "·· "),
            (token_style, symbol),
            ("", " "),
            (token_style, label),
        ]
        if self.status != "已就绪":
            fragments.extend([("", "  "), ("class:status.time", self.metric_value)])
        return fragments

    def status_text(self):
        return "".join(part for _, part in self.status_fragments())

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

    def toolbar_text(self):
        return "".join(part for _, part in self.toolbar_fragments())

    def append_message(self, role, content, *, meta=None):
        if role not in self.ROLE_STYLES:
            return
        text = self._normalize_content(content)
        if not text:
            return
        if role == "user":
            self.remember_user_input(text)
        self.transcript_entries.append({"role": role, "text": text, "meta": dict(meta or {})})

    def begin_restore(self):
        self.status = "恢复中"
        self.metric_label = "已耗时"
        self.metric_value = "0.00s"
        self._restore_started_at = perf_counter()

    def finish_restore(self):
        self.status = "已就绪"
        self.phase = "空闲"
        self.metric_value = self._elapsed_since(self._restore_started_at)
        self._restore_started_at = None

    def begin_assistant_response(self):
        self.status = "等待回复"
        self.phase = "处理中"
        self.metric_value = "0.00s"
        self._assistant_open = False
        self._assistant_entry = None
        self._response_started_at = perf_counter()
        self._response_started_iso = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    def write_assistant_chunk(self, chunk):
        if not chunk:
            return
        self._refresh_active_elapsed()
        if not self._assistant_open:
            self.transcript_entries.append({"role": "assistant", "text": "", "meta": {}})
            self._assistant_entry = self.transcript_entries[-1]
            self._assistant_open = True
            self.status = "接收回复"
        self._assistant_entry["text"] += chunk

    def finish_assistant_response(self):
        self._refresh_active_elapsed()
        if self._assistant_entry is not None:
            self._assistant_entry["meta"] = {
                "finished_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
                "elapsed_seconds": self._elapsed_seconds(),
            }
        self._assistant_open = False
        self._assistant_entry = None
        self.status = "已就绪"
        self.phase = "空闲"
        self._response_started_at = None
        self._response_started_iso = None

    def mark_error(self):
        self._refresh_active_elapsed()
        self.status = "出错"
        self.phase = "失败"
        self._assistant_open = False
        self._assistant_entry = None
        self._response_started_at = None
        self._response_started_iso = None

    def remember_user_input(self, text):
        normalized = self._normalize_content(text)
        if not normalized:
            return
        if not self.user_inputs or self.user_inputs[-1] != normalized:
            self.user_inputs.append(normalized)
        self.reset_input_replay()

    def recall_previous_input(self, current_text):
        if not self.user_inputs:
            return current_text
        if self._history_index is None:
            self._history_draft = current_text
            self._history_index = len(self.user_inputs) - 1
        elif self._history_index > 0:
            self._history_index -= 1
        return self.user_inputs[self._history_index]

    def recall_next_input(self, current_text):
        if self._history_index is None:
            return current_text
        if self._history_index < len(self.user_inputs) - 1:
            self._history_index += 1
            return self.user_inputs[self._history_index]
        draft = self._history_draft
        self.reset_input_replay()
        return draft

    def reset_input_replay(self):
        self._history_index = None
        self._history_draft = ""

    def record_debug_event(self, name):
        self.debug_event = name

    def _refresh_active_elapsed(self):
        if self._response_started_at is not None:
            self.metric_value = self._elapsed_since(self._response_started_at)
        elif self._restore_started_at is not None:
            self.metric_value = self._elapsed_since(self._restore_started_at)

    def _status_token(self):
        return self.STATUS_TOKENS.get(self.status) or ("○", "idle", "class:status.idle")

    @staticmethod
    def _assistant_separator_text(entry):
        meta = entry.get("meta", {})
        finished_at = meta.get("finished_at")
        elapsed_seconds = meta.get("elapsed_seconds")
        if finished_at and elapsed_seconds is not None:
            try:
                finished_text = datetime.fromisoformat(finished_at).strftime("%H:%M")
            except ValueError:
                finished_text = str(finished_at)
            return f"──── {finished_text} · {InteractiveChatState._format_elapsed_seconds(elapsed_seconds)}"
        return "────"

    def current_round_user_message(self, text):
        return {"role": "user", "content": text, "meta": {"started_at": self._response_started_iso}}

    def current_round_assistant_message(self):
        if not self.transcript_entries:
            return {"role": "assistant", "content": "", "meta": {}}
        entry = self.transcript_entries[-1]
        return {"role": "assistant", "content": entry["text"], "meta": dict(entry.get("meta") or {})}

    @staticmethod
    def _entry_text(entry):
        label, _, _ = InteractiveChatState.ROLE_STYLES[entry["role"]]
        return f"{label}{entry['text']}\n"

    @staticmethod
    def _elapsed_since(started_at):
        if started_at is None:
            return "-"
        return f"{max(perf_counter() - started_at, 0):.2f}s"

    def _elapsed_seconds(self):
        if self._response_started_at is None:
            return None
        return round(max(perf_counter() - self._response_started_at, 0), 2)

    @staticmethod
    def _format_elapsed_seconds(elapsed_seconds):
        if elapsed_seconds is None:
            return "-"
        return f"{float(elapsed_seconds):.2f}s"

    @staticmethod
    def _normalize_content(content):
        if isinstance(content, list):
            return "\n".join(str(item) for item in content).strip()
        return str(content).strip()


def _create_textual_app(
    state,
    *,
    client,
    model,
    prompt,
    session_path,
    temperature,
    max_output_tokens,
    history_messages,
    probe_input=False,
):
    try:
        from textual.app import App, ComposeResult
        from textual.binding import Binding
        from textual.containers import Vertical
        from textual.widgets import Footer, Input, RichLog, Static
    except ImportError as exc:
        raise click.ClickException("交互式对话需要安装 textual") from exc

    class ChatApp(App[None]):
        CSS = """
        Screen {
            layout: vertical;
        }
        #transcript {
            height: 1fr;
            border: none;
        }
        #status {
            height: 1;
            color: rgb(148,163,184);
            padding: 0 1;
        }
        #input {
            height: 3;
            min-height: 3;
            max-height: 3;
            margin: 0 1;
            padding: 0 1;
            border: round rgb(71,85,105);
            background: transparent;
        }
        #input:focus {
            border: round rgb(100,116,139);
            background: transparent;
        }
        #toolbar {
            height: 1;
            color: rgb(148,163,184);
            padding: 0 1;
        }
        Footer {
            display: none;
        }
        """

        BINDINGS = [
            Binding("up", "history_prev", show=False, priority=True),
            Binding("down", "history_next", show=False, priority=True),
            Binding("pageup", "history_page_up", show=False, priority=True),
            Binding("pagedown", "history_page_down", show=False, priority=True),
            Binding("home", "history_home", show=False, priority=True),
            Binding("end", "history_end", show=False, priority=True),
        ]

        def compose(self) -> ComposeResult:
            with Vertical():
                yield RichLog(id="transcript", wrap=True, markup=False, highlight=False, auto_scroll=False)
                yield Static(id="status")
                yield Input(placeholder="", id="input")
                yield Static(id="toolbar")
                yield Footer()

        def on_mount(self) -> None:
            self.transcript = self.query_one("#transcript", RichLog)
            self.status_widget = self.query_one("#status", Static)
            self.input_widget = self.query_one("#input", Input)
            self.toolbar_widget = self.query_one("#toolbar", Static)
            self.transcript.can_focus = False
            self.transcript.focus_on_click = False
            self._busy = False
            self._transcript_at_bottom = True
            self._refresh_status()
            self._reload_transcript()
            self.set_interval(0.2, self._tick_status)
            self.call_after_refresh(self._scroll_to_end)
            self.call_after_refresh(self.input_widget.focus)
            if prompt:
                self.call_after_refresh(lambda: self._submit_text(prompt))

        def _refresh_status(self) -> None:
            self.status_widget.update(state.status_text())
            self.toolbar_widget.update(state.toolbar_text())

        def _reload_transcript(self) -> None:
            self.transcript.clear()
            for line in state.transcript_rich_lines():
                self.transcript.write(line, scroll_end=False)
            if self._transcript_at_bottom:
                self._scroll_to_end()

        def _scroll_to_end(self) -> None:
            self.transcript.scroll_end(animate=False, immediate=True, force=True)
            self._transcript_at_bottom = True

        def _tick_status(self) -> None:
            if self._busy:
                self._refresh_status()

        def _mark_user_scrolling(self) -> None:
            self._transcript_at_bottom = False

        async def on_input_submitted(self, message: Input.Submitted) -> None:
            await self._submit_text(message.value)

        async def _submit_text(self, text: str) -> None:
            text = text.strip()
            if not text or self._busy:
                self.input_widget.value = ""
                return
            self.input_widget.value = ""
            self._busy = True
            state.append_message("user", text)
            state.message_count += 1
            state.begin_assistant_response()
            self._transcript_at_bottom = True
            self._reload_transcript()
            self._refresh_status()
            self.run_worker(self._run_round(text), exclusive=True)

        async def _run_round(self, user_text: str) -> None:
            assistant_parts = []

            def handle_chunk(chunk: str) -> None:
                assistant_parts.append(chunk)
                state.write_assistant_chunk(chunk)
                self.call_from_thread(self._on_transcript_update)

            try:
                result = await asyncio.to_thread(
                run_task,
                "chat",
                client,
                model,
                messages=_request_messages([*history_messages, {"role": "user", "content": user_text}]),
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                stream_handler=handle_chunk,
            )
            except Exception as exc:
                state.mark_error()
                self._on_round_failed(str(exc))
                return

            if not assistant_parts and result["text"]:
                state.write_assistant_chunk(result["text"])
            user_message = state.current_round_user_message(user_text)
            state.finish_assistant_response()
            state.message_count += 1
            assistant_message = state.current_round_assistant_message()
            append_session_messages(session_path, [user_message, assistant_message])
            history_messages.extend([user_message, assistant_message])
            self._on_round_complete()

        def _on_transcript_update(self) -> None:
            self._reload_transcript()
            self._refresh_status()

        def _on_round_complete(self) -> None:
            self._busy = False
            self._reload_transcript()
            self._refresh_status()

        def _on_round_failed(self, error_text: str) -> None:
            self._busy = False
            state.append_message("system", error_text)
            self._reload_transcript()
            self._refresh_status()

        def action_history_prev(self) -> None:
            if probe_input:
                state.record_debug_event("up")
                self._refresh_status()
            self.input_widget.value = state.recall_previous_input(self.input_widget.value)
            self.input_widget.cursor_position = len(self.input_widget.value)

        def action_history_next(self) -> None:
            if probe_input:
                state.record_debug_event("down")
                self._refresh_status()
            self.input_widget.value = state.recall_next_input(self.input_widget.value)
            self.input_widget.cursor_position = len(self.input_widget.value)

        def action_history_page_up(self) -> None:
            if probe_input:
                state.record_debug_event("pageup")
                self._refresh_status()
            self._mark_user_scrolling()
            self.transcript.action_page_up()

        def action_history_page_down(self) -> None:
            if probe_input:
                state.record_debug_event("pagedown")
                self._refresh_status()
            self._mark_user_scrolling()
            self.transcript.action_page_down()

        def action_history_home(self) -> None:
            if probe_input:
                state.record_debug_event("home")
                self._refresh_status()
            self._mark_user_scrolling()
            self.transcript.action_scroll_home()

        def action_history_end(self) -> None:
            if probe_input:
                state.record_debug_event("end")
                self._refresh_status()
            self._scroll_to_end()

    return ChatApp()


def run_interactive_chat(
    *,
    client,
    model,
    prompt,
    session_path,
    temperature,
    max_output_tokens,
    history_messages,
    probe_input=False,
):
    state = InteractiveChatState(model=model, session_path=session_path, history_messages=history_messages)
    if history_messages:
        state.begin_restore()
        state.finish_restore()
    app = _create_textual_app(
        state,
        client=client,
        model=model,
        prompt=prompt,
        session_path=session_path,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        history_messages=history_messages,
        probe_input=probe_input,
    )
    app.run()
