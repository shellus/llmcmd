import os
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from click.testing import CliRunner

from llm_cli.cli import cli
from llm_cli.interactive import InteractiveChatState, run_interactive_chat


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
            self.assertIn('"meta":{"finished_at":"', lines[-1])
            self.assertIn('"elapsed_seconds":', lines[-1])

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

    def test_interactive_chat_passes_input_probe_flag(self):
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
                result = runner.invoke(cli, ["chat", "-I", "--probe-input", "-s", str(session_path)])

            self.assertEqual(result.exit_code, 0)
            self.assertTrue(captured["probe_input"])

    def test_interactive_with_explicit_session_uses_given_session_path(self):
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
                    result = runner.invoke(cli, ["chat", "-I", "-s", ".llm-chat.jsonl"])
            finally:
                os.chdir(old_cwd)

            self.assertEqual(result.exit_code, 0)
            self.assertEqual(captured["session_path"], (Path(tmp) / ".llm-chat.jsonl").resolve())

    def test_interactive_without_session_does_not_create_default_session_path(self):
        captured = {}

        def fake_create_client(mode, explicit_model=None):
            return object(), "test-model", {}

        def fake_run_interactive_chat(**kwargs):
            captured.update(kwargs)

        runner = CliRunner()
        with patch("llm_cli.cli.create_client", fake_create_client), patch(
            "llm_cli.cli.run_interactive_chat", fake_run_interactive_chat
        ):
            result = runner.invoke(cli, ["chat", "-I"])

        self.assertEqual(result.exit_code, 0)
        self.assertIsNone(captured["session_path"])
        self.assertEqual(captured["history_messages"], [])

    def test_interactive_chat_passes_system_prompt_into_runner(self):
        captured = {}

        def fake_create_client(mode, explicit_model=None):
            return object(), "test-model", {}

        def fake_run_interactive_chat(**kwargs):
            captured.update(kwargs)

        runner = CliRunner()
        with patch("llm_cli.cli.create_client", fake_create_client), patch(
            "llm_cli.cli.run_interactive_chat", fake_run_interactive_chat
        ):
            result = runner.invoke(cli, ["chat", "-I", "--system", "系统设定"])

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(captured["system_prompt"], "系统设定")

    def test_single_chat_with_session_replaces_leading_system_messages(self):
        with TemporaryDirectory() as tmp:
            session_path = Path(tmp) / "demo.jsonl"
            session_path.write_text(
                '{"type":"message","role":"system","content":"旧系统"}\n'
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
                result = runner.invoke(cli, ["chat", "新问题", "-s", str(session_path), "--system", "新系统"])

            self.assertEqual(result.exit_code, 0)
            self.assertEqual(
                captured["messages"],
                [
                    {"role": "system", "content": "新系统"},
                    {"role": "user", "content": "旧问题"},
                    {"role": "assistant", "content": "旧回答"},
                    {"role": "user", "content": "新问题"},
                ],
            )
            lines = session_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertIn('"role":"system"', lines[0])
            self.assertIn("新系统", lines[0])

    def test_single_chat_with_new_session_writes_system_message_first(self):
        with TemporaryDirectory() as tmp:
            session_path = Path(tmp) / "demo.jsonl"

            def fake_create_client(mode, explicit_model=None):
                return object(), "test-model", {}

            def fake_run_task(mode, client, model, **kwargs):
                return {"mode": mode, "text": "回答", "printed": True}

            runner = CliRunner()
            with patch("llm_cli.cli.create_client", fake_create_client), patch("llm_cli.cli.run_task", fake_run_task):
                result = runner.invoke(cli, ["chat", "新问题", "-s", str(session_path), "--system", "系统设定"])

            self.assertEqual(result.exit_code, 0)
            lines = session_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertIn('"role":"system"', lines[0])
            self.assertIn("系统设定", lines[0])

    def test_state_replays_history_and_updates_toolbar(self):
        state = InteractiveChatState(
            model="test-model",
            session_path=Path("/tmp/demo.jsonl"),
            history_messages=[
                {"role": "user", "content": "旧问题"},
                {
                    "role": "assistant",
                    "content": "旧回答",
                    "meta": {"finished_at": "2026-03-23T14:32:07+08:00", "elapsed_seconds": 6.83},
                },
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
        self.assertEqual(status_text, "·· ○ idle")
        separator = state.transcript_lines()[2][0][1]
        self.assertEqual(separator, "──── 14:32 · 6.83s")

    def test_state_toolbar_marks_non_persistent_session(self):
        state = InteractiveChatState(
            model="test-model",
            session_path=None,
            history_messages=[],
        )

        toolbar_text = "".join(part for _, part in state.toolbar_fragments())
        self.assertIn("会话: 未持久化", toolbar_text)

    def test_load_session_messages_preserves_meta_for_history_separator(self):
        from llm_cli.session import load_session_messages

        with TemporaryDirectory() as tmp:
            session_path = Path(tmp) / "demo.jsonl"
            session_path.write_text(
                '{"type":"message","role":"user","content":"你好","meta":{"started_at":"2026-03-23T14:32:01+08:00"}}\n'
                '{"type":"message","role":"assistant","content":"你好。","meta":{"finished_at":"2026-03-23T14:32:07+08:00","elapsed_seconds":6.83}}\n',
                encoding="utf-8",
            )

            messages = load_session_messages(session_path)

        self.assertEqual(
            messages,
            [
                {"role": "user", "content": "你好", "meta": {"started_at": "2026-03-23T14:32:01+08:00"}},
                {
                    "role": "assistant",
                    "content": "你好。",
                    "meta": {"finished_at": "2026-03-23T14:32:07+08:00", "elapsed_seconds": 6.83},
                },
            ],
        )

    def test_state_streaming_updates_status_and_transcript(self):
        state = InteractiveChatState(
            model="test-model",
            session_path=Path("/tmp/demo.jsonl"),
            history_messages=[],
        )

        state.begin_assistant_response()
        status_text = "".join(part for _, part in state.status_fragments())
        self.assertIn("·· ↻ wait", status_text)

        state.write_assistant_chunk("第一段")
        status_text = "".join(part for _, part in state.status_fragments())
        self.assertIn("·· ⇣ wait", status_text)
        state.write_assistant_chunk("第二段")
        state.finish_assistant_response()

        status_text = "".join(part for _, part in state.status_fragments())
        self.assertEqual(status_text, "·· ○ idle")
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
        self.assertEqual(status_text, "·· ○ idle")

    def test_state_wait_duration_updates_without_chunks(self):
        state = InteractiveChatState(
            model="test-model",
            session_path=Path("/tmp/demo.jsonl"),
            history_messages=[],
        )

        state.begin_assistant_response()
        first_status = "".join(part for _, part in state.status_fragments())
        time.sleep(0.02)
        second_status = "".join(part for _, part in state.status_fragments())

        self.assertIn("·· ↻ wait", first_status)
        self.assertIn("·· ↻ wait", second_status)
        self.assertNotEqual(first_status, second_status)

    def test_status_fragments_color_status_token_and_keep_time_gray(self):
        state = InteractiveChatState(
            model="test-model",
            session_path=Path("/tmp/demo.jsonl"),
            history_messages=[],
        )

        state.begin_restore()
        fragments = state.status_fragments()

        self.assertEqual(fragments[0], ("class:status.prefix", "·· "))
        self.assertEqual(fragments[1], ("class:status.load", "↻"))
        self.assertEqual(fragments[3], ("class:status.load", "load"))
        self.assertEqual(fragments[-1][0], "class:status.time")

    def test_user_input_history_replays_previous_messages(self):
        state = InteractiveChatState(
            model="test-model",
            session_path=Path("/tmp/demo.jsonl"),
            history_messages=[
                {"role": "user", "content": "第一句"},
                {"role": "assistant", "content": "回答"},
                {"role": "user", "content": "第二句"},
            ],
        )

        self.assertEqual(state.recall_previous_input(""), "第二句")
        self.assertEqual(state.recall_previous_input(""), "第一句")
        self.assertEqual(state.recall_next_input(""), "第二句")
        self.assertEqual(state.recall_next_input(""), "")

    def test_user_input_history_keeps_current_draft_when_replaying(self):
        state = InteractiveChatState(
            model="test-model",
            session_path=Path("/tmp/demo.jsonl"),
            history_messages=[],
        )

        state.remember_user_input("第一句")
        state.remember_user_input("第二句")

        self.assertEqual(state.recall_previous_input("草稿"), "第二句")
        self.assertEqual(state.recall_previous_input("第二句"), "第一句")
        self.assertEqual(state.recall_next_input("第一句"), "第二句")
        self.assertEqual(state.recall_next_input("第二句"), "草稿")

    def test_transcript_lines_include_role_prefix_and_indented_wrapped_lines(self):
        state = InteractiveChatState(
            model="test-model",
            session_path=Path("/tmp/demo.jsonl"),
            history_messages=[],
        )

        state.append_message("assistant", "第一行\n第二行")
        state.append_message("user", "用户消息")

        lines = state.transcript_lines()
        self.assertEqual(lines[0][0][1], "AI  ")
        self.assertEqual(lines[0][1][1], "第一行")
        self.assertEqual(lines[1][0][1], "    ")
        self.assertEqual(lines[1][1][1], "第二行")
        self.assertEqual(lines[2][0][1], "────")
        self.assertEqual(lines[3][0][1], "你  ")

    def test_transcript_lines_add_separator_after_assistant_reply(self):
        state = InteractiveChatState(
            model="test-model",
            session_path=Path("/tmp/demo.jsonl"),
            history_messages=[],
        )

        state.append_message("user", "用户消息")
        state.append_message("assistant", "助手消息")

        lines = state.transcript_lines()
        self.assertEqual(lines[0][0][1], "你  ")
        self.assertEqual(lines[1][0][1], "AI  ")
        self.assertEqual(lines[2][0][1], "────")
        self.assertIn("assistant.separator", lines[2][0][0])

    def test_assistant_separator_contains_time_and_elapsed(self):
        state = InteractiveChatState(
            model="test-model",
            session_path=Path("/tmp/demo.jsonl"),
            history_messages=[],
        )

        state.begin_assistant_response()
        state.write_assistant_chunk("助手消息")
        time.sleep(0.01)
        state.finish_assistant_response()

        separator = state.transcript_lines()[1][0][1]
        self.assertRegex(separator, r"^──── \d{2}:\d{2} · \d+\.\d{2}s$")
        self.assertRegex(
            state.transcript_entries[0]["meta"]["finished_at"],
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$",
        )
        self.assertGreater(state.transcript_entries[0]["meta"]["elapsed_seconds"], 0)


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

    def test_interactive_without_session_path_resolves_to_none(self):
        from llm_cli.session import resolve_session_path

        with TemporaryDirectory() as tmp:
            resolved = resolve_session_path(None, cwd=tmp, interactive=True)
            self.assertIsNone(resolved)

    def test_resolve_model_uses_new_two_level_model_chain(self):
        from llm_cli.config import resolve_model

        config = {
            "MODEL": "global-model",
            "CHAT_MODEL": "chat-model",
            "IMAGE_MODEL": "image-model",
            "AUDIO_MODEL": "audio-model",
        }

        self.assertEqual(resolve_model("chat", config), "chat-model")
        self.assertEqual(resolve_model("text", config), "chat-model")
        self.assertEqual(resolve_model("image", config), "image-model")
        self.assertEqual(resolve_model("audio", config), "audio-model")

    def test_resolve_model_falls_back_to_global_model(self):
        from llm_cli.config import resolve_model

        config = {"MODEL": "global-model"}

        self.assertEqual(resolve_model("chat", config), "global-model")
        self.assertEqual(resolve_model("image", config), "global-model")
        self.assertEqual(resolve_model("audio", config), "global-model")

    def test_write_env_value_updates_existing_key_and_preserves_others(self):
        from llm_cli.config import write_env_value

        with TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("API_KEY=demo\nCHAT_MODEL=old-chat\nMODEL=global\n", encoding="utf-8")

            write_env_value(env_path, "CHAT_MODEL", "new-chat")

            self.assertEqual(
                env_path.read_text(encoding="utf-8"),
                "API_KEY=demo\nCHAT_MODEL=new-chat\nMODEL=global\n",
            )

    def test_write_env_value_appends_missing_key(self):
        from llm_cli.config import write_env_value

        with TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("API_KEY=demo\n", encoding="utf-8")

            write_env_value(env_path, "CHAT_MODEL", "new-chat")

            self.assertEqual(
                env_path.read_text(encoding="utf-8"),
                "API_KEY=demo\nCHAT_MODEL=new-chat\n",
            )

    def test_parse_builtin_command_supports_clear_model_and_save(self):
        from llm_cli.interactive import parse_builtin_command

        self.assertEqual(parse_builtin_command("/clear"), ("clear", ""))
        self.assertEqual(parse_builtin_command("/model gpt-5"), ("model", "gpt-5"))
        self.assertEqual(parse_builtin_command("/save worklog"), ("save", "worklog"))
        self.assertEqual(parse_builtin_command("普通消息"), (None, None))

    def test_normalize_composer_text_preserves_internal_newlines(self):
        from llm_cli.interactive import normalize_composer_text

        self.assertEqual(normalize_composer_text("第一行\n第二行\n"), "第一行\n第二行")
        self.assertEqual(normalize_composer_text("\n  第一行\n第二行  \n"), "第一行\n第二行")
        self.assertIsNone(normalize_composer_text(" \n\t "))

    def test_calculate_composer_widget_height_includes_border_space(self):
        from llm_cli.interactive import calculate_composer_widget_height

        self.assertEqual(calculate_composer_widget_height(0), 3)
        self.assertEqual(calculate_composer_widget_height(1), 3)
        self.assertEqual(calculate_composer_widget_height(7), 9)
        self.assertEqual(calculate_composer_widget_height(20), 17)

    def test_finalize_failed_round_persists_partial_assistant_and_error(self):
        from llm_cli.interactive import InteractiveChatState, finalize_failed_round

        with TemporaryDirectory() as tmp:
            session_path = Path(tmp) / "failed.jsonl"
            history_messages = []
            state = InteractiveChatState(
                model="test-model",
                session_path=session_path,
                history_messages=[],
            )

            state.append_message("user", "新问题")
            state.message_count += 1
            state.begin_assistant_response()
            state.write_assistant_chunk("已输出一半")
            state.mark_error()

            finalize_failed_round(
                state=state,
                history_messages=history_messages,
                user_text="新问题",
                error_text="网络中断",
            )

            self.assertEqual(
                history_messages,
                [
                    {"role": "user", "content": "新问题", "meta": {"started_at": None}},
                    {"role": "assistant", "content": "已输出一半", "meta": {}},
                    {"role": "system", "content": "网络中断"},
                ],
            )
            lines = session_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 3)
            self.assertIn('"role":"assistant"', lines[1])
            self.assertIn("已输出一半", lines[1])
            self.assertIn('"role":"system"', lines[2])
            self.assertIn("网络中断", lines[2])

    def test_finalize_successful_round_persists_user_and_assistant(self):
        from llm_cli.interactive import InteractiveChatState, finalize_successful_round

        with TemporaryDirectory() as tmp:
            session_path = Path(tmp) / "success.jsonl"
            history_messages = []
            state = InteractiveChatState(
                model="test-model",
                session_path=session_path,
                history_messages=[],
            )

            state.append_message("user", "输出出师表全文")
            state.message_count += 1
            state.begin_assistant_response()
            state.write_assistant_chunk("先帝创业未半")
            state.finish_assistant_response()

            finalize_successful_round(
                state=state,
                history_messages=history_messages,
                user_text="输出出师表全文",
            )

            self.assertEqual(
                history_messages,
                [
                    {"role": "user", "content": "输出出师表全文", "meta": {"started_at": None}},
                    {
                        "role": "assistant",
                        "content": "先帝创业未半",
                        "meta": state.transcript_entries[-1]["meta"],
                    },
                ],
            )
            lines = session_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 2)
            self.assertIn('"role":"user"', lines[0])
            self.assertIn('"role":"assistant"', lines[1])

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
