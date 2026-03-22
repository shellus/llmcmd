import os
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from click.testing import CliRunner

from llm_cli.cli import cli
from llm_cli.interactive import InteractiveChatState, _TranscriptLexer


class ChatSessionTests(unittest.TestCase):
    def test_image_command_passes_all_references_to_run_task(self):
        captured = {}

        def fake_create_client(mode, explicit_model=None):
            return object(), "test-image-model", {}

        def fake_run_task(mode, client, model, **kwargs):
            captured["reference"] = kwargs["reference"]
            return {"mode": mode, "output_paths": ["/tmp/result.jpg"], "printed": False}

        runner = CliRunner()
        with patch("llm_cli.cli.create_client", fake_create_client), patch("llm_cli.cli.run_task", fake_run_task):
            result = runner.invoke(cli, ["image", "测试", "-r", "first.jpg", "-r", "second.jpg"])

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(captured["reference"], ("first.jpg", "second.jpg"))

    def test_image_command_passes_input_files_to_run_task(self):
        captured = {}

        def fake_create_client(mode, explicit_model=None):
            return object(), "test-image-model", {}

        def fake_run_task(mode, client, model, **kwargs):
            captured["input_paths"] = kwargs["input_paths"]
            return {"mode": mode, "output_paths": ["/tmp/result.jpg"], "printed": False}

        runner = CliRunner()
        with patch("llm_cli.cli.create_client", fake_create_client), patch("llm_cli.cli.run_task", fake_run_task):
            result = runner.invoke(cli, ["image", "测试", "-i", "constraint-a.md", "-i", "constraint-b.md"])

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(captured["input_paths"], ("constraint-a.md", "constraint-b.md"))

    def test_single_chat_with_session_loads_history_and_appends(self):
        with TemporaryDirectory() as tmp:
            session_path = Path(tmp) / "demo.jsonl"
            session_path.write_text(
                '{"type":"message","role":"user","content":"旧问题"}\n'
                '{"type":"message","role":"assistant","content":"旧回答"}\n',
                encoding="utf-8",
            )

            captured = {}

            def fake_create_client(mode, explicit_model=None):
                return object(), "test-model", {}

            def fake_run_task(mode, client, model, **kwargs):
                captured["messages"] = kwargs["messages"]
                return {"mode": mode, "text": "新回答", "printed": True}

            runner = CliRunner()
            with patch("llm_cli.cli.create_client", fake_create_client), patch("llm_cli.cli.run_task", fake_run_task):
                result = runner.invoke(cli, ["chat", "新问题", "-s", str(session_path)])

            self.assertEqual(result.exit_code, 0)
            self.assertIn("新回答", result.output)
            self.assertEqual(
                captured["messages"],
                [
                    {"role": "user", "content": "旧问题"},
                    {"role": "assistant", "content": "旧回答"},
                    {"role": "user", "content": "新问题"},
                ],
            )
            lines = session_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 4)
            self.assertIn('"role":"assistant"', lines[-1])
            self.assertIn("新回答", lines[-1])

    def test_interactive_chat_delegates_to_runner(self):
        with TemporaryDirectory() as tmp:
            session_path = Path(tmp) / "interactive.jsonl"
            captured = {}

            def fake_create_client(mode, explicit_model=None):
                return object(), "test-model", {}

            def fake_run_interactive_chat(**kwargs):
                captured.update(kwargs)

            runner = CliRunner()
            with patch("llm_cli.cli.create_client", fake_create_client), patch(
                "llm_cli.cli.run_interactive_chat", fake_run_interactive_chat
            ):
                result = runner.invoke(cli, ["chat", "-I", "-s", str(session_path), "你好"])

            self.assertEqual(result.exit_code, 0)
            self.assertEqual(captured["model"], "test-model")
            self.assertEqual(captured["prompt"], "你好")
            self.assertEqual(captured["session_path"], session_path.resolve())

    def test_interactive_defaults_to_hidden_session_file_in_cwd(self):
        with TemporaryDirectory() as tmp:
            captured = {}

            def fake_create_client(mode, explicit_model=None):
                return object(), "test-model", {}

            def fake_run_interactive_chat(**kwargs):
                captured.update(kwargs)

            runner = CliRunner()
            old_cwd = os.getcwd()
            try:
                os.chdir(tmp)
                with patch("llm_cli.cli.create_client", fake_create_client), patch(
                    "llm_cli.cli.run_interactive_chat", fake_run_interactive_chat
                ):
                    result = runner.invoke(cli, ["chat", "-I"])
            finally:
                os.chdir(old_cwd)

            self.assertEqual(result.exit_code, 0)
            self.assertEqual(captured["session_path"], (Path(tmp) / ".llm-chat.jsonl").resolve())

    def test_state_replays_history_and_updates_toolbar(self):
        state = InteractiveChatState(
            model="test-model",
            session_path=Path("/tmp/demo.jsonl"),
            history_messages=[
                {"role": "user", "content": "旧问题"},
                {"role": "assistant", "content": "旧回答"},
            ],
        )

        self.assertIn("旧问题", state.transcript_text)
        self.assertIn("旧回答", state.transcript_text)
        toolbar = state.toolbar_fragments()
        status_bar = state.status_fragments()
        toolbar_text = "".join(part for _, part in toolbar)
        status_text = "".join(part for _, part in status_bar)
        self.assertIn("模型: test-model", toolbar_text)
        self.assertIn("消息: 2", toolbar_text)
        self.assertIn("会话: demo", toolbar_text)
        self.assertIn("状态: 已就绪", status_text)
        self.assertIn("阶段: 空闲", status_text)
        self.assertIn("上轮耗时: -", status_text)

    def test_state_streaming_updates_status_and_transcript(self):
        state = InteractiveChatState(
            model="test-model",
            session_path=Path("/tmp/demo.jsonl"),
            history_messages=[],
        )

        state.begin_assistant_response()
        status_text = "".join(part for _, part in state.status_fragments())
        self.assertIn("状态: 等待首字", status_text)
        self.assertIn("本轮耗时:", status_text)

        state.write_assistant_chunk("第一段")
        state.write_assistant_chunk("第二段")
        state.finish_assistant_response()

        status_text = "".join(part for _, part in state.status_fragments())
        self.assertIn("状态: 已就绪", status_text)
        self.assertIn("阶段: 回复完成", status_text)
        self.assertIn("上轮耗时:", status_text)
        self.assertIn("第一段第二段", state.transcript_text)

    def test_state_tracks_restore_duration(self):
        state = InteractiveChatState(
            model="test-model",
            session_path=Path("/tmp/demo.jsonl"),
            history_messages=[],
        )

        state.begin_restore()
        time.sleep(0.01)
        state.finish_restore()

        status_text = "".join(part for _, part in state.status_fragments())
        self.assertIn("状态: 已就绪", status_text)
        self.assertIn("阶段: 恢复完成", status_text)
        self.assertIn("恢复耗时:", status_text)

    def test_transcript_fragments_separate_role_and_content_styles(self):
        state = InteractiveChatState(
            model="test-model",
            session_path=Path("/tmp/demo.jsonl"),
            history_messages=[],
        )

        state.append_message("user", "用户消息")
        state.append_message("assistant", "助手消息")
        state.append_message("system", "系统消息")

        fragments = state.transcript_fragments()

        self.assertIn(("class:role.user", "你  "), fragments)
        self.assertIn(("class:role.assistant", "AI  "), fragments)
        self.assertIn(("class:role.system", "系统"), fragments)
        self.assertIn(("class:message.user", "用户消息"), fragments)
        self.assertIn(("class:message.assistant", "助手消息"), fragments)
        self.assertIn(("class:message.system", "系统消息"), fragments)

    def test_transcript_lexer_colors_role_prefixes(self):
        from prompt_toolkit.document import Document

        lexer = _TranscriptLexer()
        get_line = lexer.lex_document(
            Document(
                text="你  用户消息\nAI  助手消息\n系统系统消息\n普通文本",
            )
        )

        self.assertEqual(get_line(0), [("class:role.user", "你  "), ("class:message.user", "用户消息")])
        self.assertEqual(get_line(1), [("class:role.assistant", "AI  "), ("class:message.assistant", "助手消息")])
        self.assertEqual(get_line(2), [("class:role.system", "系统"), ("class:message.system", "系统消息")])
        self.assertEqual(get_line(3), [("", "普通文本")])

    def test_session_name_resolves_to_jsonl_in_current_directory(self):
        from llm_cli.session import resolve_session_path

        with TemporaryDirectory() as tmp:
            resolved = resolve_session_path("demo", cwd=tmp)
            self.assertEqual(resolved, (Path(tmp) / "demo.jsonl").resolve())

    def test_session_path_keeps_explicit_jsonl_suffix(self):
        from llm_cli.session import resolve_session_path

        with TemporaryDirectory() as tmp:
            resolved = resolve_session_path("./sessions/demo.jsonl", cwd=tmp)
            self.assertEqual(resolved, (Path(tmp) / "sessions" / "demo.jsonl").resolve())

    def test_build_messages_keeps_multiple_reference_images_for_image_mode(self):
        from llm_cli.messages import build_messages

        with TemporaryDirectory() as tmp:
            first = Path(tmp) / "first.jpg"
            second = Path(tmp) / "second.jpg"
            first.write_bytes(b"first-image")
            second.write_bytes(b"second-image")

            messages = build_messages("image", prompt="测试提示词", reference_path=[str(first), str(second)])

        self.assertEqual(len(messages), 1)
        content = messages[0]["content"]
        image_parts = [part for part in content if part["type"] == "image_url"]
        text_parts = [part for part in content if part["type"] == "text"]
        self.assertEqual(len(image_parts), 2)
        self.assertEqual(text_parts, [{"type": "text", "text": "测试提示词"}])

    def test_build_messages_merges_image_prompt_and_input_text(self):
        from llm_cli.messages import build_messages

        messages = build_messages("image", prompt="主要求", input_text="补充约束")

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["role"], "user")
        self.assertEqual(messages[0]["content"], "主要求\n\n补充约束")


if __name__ == "__main__":
    unittest.main()
