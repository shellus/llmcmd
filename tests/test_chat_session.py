import os
import time
import unittest
from types import SimpleNamespace
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from click.testing import CliRunner

from llm_cli.cli import cli
from llm_cli.interactive import InteractiveChatState, run_interactive_chat


class ChatSessionTests(unittest.TestCase):
    def test_api_call_stream_collects_image_deltas(self):
        from llm_cli.api import api_call

        image_url = "data:image/png;base64,AAAA"
        stream = [
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            content=None,
                            refusal=None,
                            role="assistant",
                            images=[{"type": "image_url", "image_url": {"url": image_url}}],
                        )
                    )
                ]
            ),
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content="", refusal=None, role="assistant", images=None)
                    )
                ]
            ),
        ]

        client = SimpleNamespace(
            base_url="https://example.com/v1",
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=lambda **kwargs: stream)
            ),
        )

        response = api_call(client, "test-model", [{"role": "user", "content": "测试"}])

        self.assertEqual(response.choices[0].message.content, "")
        self.assertEqual(response.choices[0].message.images, [{"type": "image_url", "image_url": {"url": image_url}}])

    def test_sanitize_debug_value_truncates_response_base64(self):
        from llm_cli.api import sanitize_debug_value

        image_url = "data:image/png;base64," + ("A" * 300)
        sanitized = sanitize_debug_value(
            [{"type": "image_url", "image_url": {"url": image_url}}],
            limit=50,
        )

        self.assertIn("...<truncated, total", sanitized[0]["image_url"]["url"])
        self.assertNotEqual(sanitized[0]["image_url"]["url"], image_url)

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

    def test_image_command_passes_size_and_aspect_to_run_task(self):
        captured = {}

        def fake_create_client(mode, explicit_model=None):
            return object(), "test-image-model", {}

        def fake_run_task(mode, client, model, **kwargs):
            captured["image_size"] = kwargs["image_size"]
            captured["image_aspect_ratio"] = kwargs["image_aspect_ratio"]
            return {"mode": mode, "output_paths": ["/tmp/result.jpg"], "printed": False}

        runner = CliRunner()
        with patch("llm_cli.cli.create_client", fake_create_client), patch("llm_cli.cli.run_task", fake_run_task):
            result = runner.invoke(cli, ["image", "测试", "--size", "2K", "--aspect", "16:9"])

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(captured["image_size"], "2K")
        self.assertEqual(captured["image_aspect_ratio"], "16:9")

    def test_image_command_rejects_removed_input_option(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["image", "测试", "-i", "constraint-a.md"])
        self.assertNotEqual(result.exit_code, 0)

    def test_chat_command_passes_all_references_to_run_task(self):
        captured = {}

        def fake_create_client(mode, explicit_model=None):
            return object(), "test-model", {}

        def fake_run_task(mode, client, model, **kwargs):
            captured["reference"] = kwargs["reference"]
            return {"mode": mode, "text": "回答", "printed": True}

        runner = CliRunner()
        with patch("llm_cli.cli.create_client", fake_create_client), patch("llm_cli.cli.run_task", fake_run_task):
            result = runner.invoke(cli, ["chat", "分析附件", "-r", "a.txt", "-r", "b.png"])

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(captured["reference"], ("a.txt", "b.png"))

    def test_chat_command_rejects_removed_input_option(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["chat", "分析", "-i", "note.txt"])
        self.assertNotEqual(result.exit_code, 0)

    def test_chat_command_renders_output_paths_when_chat_model_returns_image(self):
        def fake_create_client(mode, explicit_model=None):
            return object(), "test-model", {}

        def fake_run_task(mode, client, model, **kwargs):
            return {"mode": mode, "output_paths": ["/tmp/chat-image.jpg"], "printed": False}

        runner = CliRunner()
        with patch("llm_cli.cli.create_client", fake_create_client), patch("llm_cli.cli.run_task", fake_run_task):
            result = runner.invoke(cli, ["chat", "画一只猫"])

        self.assertEqual(result.exit_code, 0)
        self.assertIn("已写入图片: /tmp/chat-image.jpg", result.output)

    def test_chat_command_passes_stream_handler_for_noninteractive_stdout(self):
        captured = {}

        def fake_create_client(mode, explicit_model=None):
            return object(), "test-model", {}

        def fake_run_task(mode, client, model, **kwargs):
            captured["stream_handler"] = kwargs.get("stream_handler")
            return {"mode": mode, "text": "回答", "printed": True}

        runner = CliRunner()
        with patch("llm_cli.cli.create_client", fake_create_client), patch("llm_cli.cli.run_task", fake_run_task):
            result = runner.invoke(cli, ["chat", "你好"])

        self.assertEqual(result.exit_code, 0)
        self.assertTrue(callable(captured["stream_handler"]))

    def test_stream_to_stdout_flushes_immediately(self):
        from llm_cli import cli as cli_module

        class FakeStdout:
            def __init__(self):
                self.buffer = []
                self.flush_count = 0

            def write(self, text):
                self.buffer.append(text)

            def flush(self):
                self.flush_count += 1

        fake_stdout = FakeStdout()
        with patch.object(cli_module.sys, "stdout", fake_stdout):
            cli_module._stream_to_stdout("分片内容")

        self.assertEqual("".join(fake_stdout.buffer), "分片内容")
        self.assertEqual(fake_stdout.flush_count, 1)

    def test_run_task_chat_returns_output_paths_when_response_contains_images(self):
        from llm_cli.task import run_task

        response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=None,
                        images=[{"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}],
                        refusal=None,
                    )
                )
            ]
        )

        with TemporaryDirectory() as tmp:
            with patch("llm_cli.task.api_call", lambda *args, **kwargs: response):
                result = run_task(
                    "chat",
                    object(),
                    "test-model",
                    prompt="生成图片",
                    output=str(Path(tmp) / "chat-image.png"),
                )

        self.assertEqual(result["mode"], "chat")
        self.assertEqual(len(result["output_paths"]), 1)
        self.assertTrue(result["output_paths"][0].endswith("chat-image.png"))

    def test_audio_command_uses_prompt_argument_and_reference_file(self):
        captured = {}

        def fake_create_client(mode, explicit_model=None):
            return object(), "test-model", {}

        def fake_run_task(mode, client, model, **kwargs):
            captured.update(kwargs)
            kwargs["stream_handler"]("输出内容")
            return {"mode": mode, "text": "输出内容", "printed": True}

        runner = CliRunner()
        with patch("llm_cli.cli.create_client", fake_create_client), patch("llm_cli.cli.run_task", fake_run_task):
            result = runner.invoke(cli, ["audio", "总结录音内容", "-r", "demo.m4a"])

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(captured["prompt"], "总结录音内容")
        self.assertEqual(captured["audio_file"], "demo.m4a")
        self.assertIsNone(captured["output"])
        self.assertTrue(callable(captured["stream_handler"]))
        self.assertIn("输出内容", result.output)

    def test_audio_command_requires_reference_audio_file(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["audio", "总结录音内容"])
        self.assertNotEqual(result.exit_code, 0)

    def test_build_messages_chat_inlines_text_and_keeps_image_url_references(self):
        from llm_cli.messages import build_messages

        with patch("llm_cli.messages.load_binary_attachment") as mock_load, patch(
            "llm_cli.messages.read_text_attachment"
        ) as mock_text:
            mock_text.return_value = {"path": "/tmp/a.txt", "content": "文本附件内容", "language": "txt"}
            mock_load.return_value = {"path": "/tmp/b.png", "mime_type": "image/png", "base64_data": "Qg=="}
            messages = build_messages("chat", prompt="分析这些附件", reference_path=["/tmp/a.txt", "/tmp/b.png"])

        self.assertEqual(len(messages), 1)
        content = messages[0]["content"]
        self.assertEqual(content[0], {"type": "text", "text": "分析这些附件"})
        self.assertEqual(content[1]["type"], "text")
        self.assertIn("[文件: a.txt]", content[1]["text"])
        self.assertIn("```txt", content[1]["text"])
        self.assertIn("文本附件内容", content[1]["text"])
        self.assertEqual(content[2]["type"], "image_url")
        self.assertEqual(content[2]["image_url"]["url"], "data:image/png;base64,Qg==")

    def test_build_messages_chat_rejects_unsupported_binary_reference(self):
        from llm_cli.messages import build_messages

        with patch("llm_cli.messages.is_text_attachment", return_value=False), patch(
            "llm_cli.messages.is_image_attachment", return_value=False
        ):
            with self.assertRaises(SystemExit):
                build_messages("chat", prompt="分析附件", reference_path=["/tmp/demo.bin"])

    def test_build_messages_image_uses_file_parts_for_references(self):
        from llm_cli.messages import build_messages

        with patch("llm_cli.messages.load_binary_attachment") as mock_load:
            mock_load.return_value = {"path": "/tmp/ref.png", "mime_type": "image/png", "base64_data": "QQ=="}
            messages = build_messages("image", prompt="保留主体重绘", reference_path=["/tmp/ref.png"])

        content = messages[0]["content"]
        self.assertEqual(content[0]["type"], "file")
        self.assertEqual(content[0]["file"]["filename"], "ref.png")
        self.assertEqual(content[1], {"type": "text", "text": "保留主体重绘"})

    def test_debug_logs_include_stream_true(self):
        from llm_cli import api as api_module

        client = SimpleNamespace(
            base_url="https://example.com/v1",
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **kwargs: [
                        SimpleNamespace(
                            choices=[
                                SimpleNamespace(
                                    delta=SimpleNamespace(content="测试", refusal=None, role="assistant", images=None)
                                )
                            ]
                        )
                    ]
                )
            ),
        )

        stderr = StringIO()
        old_stderr = os.sys.stderr
        old_debug = api_module.DEBUG
        os.sys.stderr = stderr
        api_module.set_debug(True)
        try:
            api_module.api_call(client, "test-model", [{"role": "user", "content": "hi"}])
        finally:
            os.sys.stderr = old_stderr
            api_module.set_debug(old_debug)

        self.assertIn('"stream": true', stderr.getvalue().lower())

    def test_api_call_passes_image_config_through_extra_body(self):
        from llm_cli.api import api_call

        captured = {}
        stream = [
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="", refusal=None, role="assistant", images=None))]
            )
        ]

        def fake_create(**kwargs):
            captured.update(kwargs)
            return stream

        client = SimpleNamespace(
            base_url="https://example.com/v1",
            chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create)),
        )

        api_call(
            client,
            "test-model",
            [{"role": "user", "content": "测试"}],
            extra_body={
                "modalities": ["image", "text"],
                "image_config": {"image_size": "2K", "aspect_ratio": "16:9"},
            },
        )

        self.assertEqual(captured["extra_body"]["modalities"], ["image", "text"])
        self.assertEqual(captured["extra_body"]["image_config"]["image_size"], "2K")
        self.assertEqual(captured["extra_body"]["image_config"]["aspect_ratio"], "16:9")

    def test_video_api_debug_logs_include_request_and_response(self):
        from llm_cli import api as api_module

        stderr = StringIO()
        old_stderr = os.sys.stderr
        old_debug = api_module.DEBUG
        os.sys.stderr = stderr
        api_module.set_debug(True)

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"id":"vid_123","status":"completed"}'

        client = SimpleNamespace(base_url="https://example.com/v1", api_key="sk-test")

        try:
            with patch("llm_cli.api.urllib.request.urlopen", lambda request, timeout=300: FakeResponse()):
                api_module.get_video_task(client, "vid_123")
        finally:
            os.sys.stderr = old_stderr
            api_module.set_debug(old_debug)

        log = stderr.getvalue()
        self.assertIn("视频请求方法:", log)
        self.assertIn("/videos/vid_123", log)
        self.assertIn("视频响应:", log)

    def test_video_api_debug_logs_include_newapi_request_body_summary(self):
        from llm_cli import api as api_module

        stderr = StringIO()
        old_stderr = os.sys.stderr
        old_debug = api_module.DEBUG
        os.sys.stderr = stderr
        api_module.set_debug(True)

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"id":"vid_123","status":"processing"}'

        client = SimpleNamespace(base_url="https://example.com/v1", api_key="sk-test")

        try:
            with patch("llm_cli.api.urllib.request.urlopen", lambda request, timeout=300: FakeResponse()):
                api_module.create_video_task(
                    client,
                    model="grok-video-3",
                    prompt="test prompt",
                    size="720P",
                    reference_urls=["https://signed.example.com/a.jpg?x=1"],
                    config={"mode": {"protocol": "unified-video"}},
                )
        finally:
            os.sys.stderr = old_stderr
            api_module.set_debug(old_debug)

        log = stderr.getvalue()
        self.assertIn("视频请求体:", log)
        self.assertIn('"model": "grok-video-3"', log)
        self.assertIn('"size": "720P"', log)
        self.assertIn('"images"', log)

    def test_video_api_debug_logs_http_error_body(self):
        from llm_cli import api as api_module

        stderr = StringIO()
        old_stderr = os.sys.stderr
        old_debug = api_module.DEBUG
        os.sys.stderr = stderr
        api_module.set_debug(True)

        class FakeHTTPError(api_module.urllib.error.HTTPError):
            def __init__(self):
                super().__init__(
                    url="https://example.com/v1/videos",
                    code=403,
                    msg="Forbidden",
                    hdrs={"Content-Type": "application/json"},
                    fp=None,
                )

            def read(self):
                return b'{"error":{"message":"forbidden","type":"permission_error"}}'

        client = SimpleNamespace(base_url="https://example.com/v1", api_key="sk-test")

        try:
            with patch("llm_cli.api.urllib.request.urlopen", side_effect=FakeHTTPError()):
                with self.assertRaises(api_module.urllib.error.HTTPError):
                    api_module.get_video_task(client, "vid_123")
        finally:
            os.sys.stderr = old_stderr
            api_module.set_debug(old_debug)

        log = stderr.getvalue()
        self.assertIn("视频错误状态: 403", log)
        self.assertIn("视频错误响应体:", log)
        self.assertIn("permission_error", log)

    def test_video_headers_include_default_user_agent(self):
        from llm_cli.api import _json_headers

        client = SimpleNamespace(api_key="sk-test")
        headers = _json_headers(client)

        self.assertIn("User-Agent", headers)
        self.assertTrue(headers["User-Agent"])

    def test_video_headers_allow_user_agent_override_from_env(self):
        from llm_cli import api as api_module

        client = SimpleNamespace(api_key="sk-test")
        old_value = os.environ.get("USER_AGENT")
        os.environ["USER_AGENT"] = "curl/8.5.0"
        try:
            headers = api_module._json_headers(client)
        finally:
            if old_value is None:
                os.environ.pop("USER_AGENT", None)
            else:
                os.environ["USER_AGENT"] = old_value

        self.assertEqual(headers["User-Agent"], "curl/8.5.0")

    def test_batch_image_task_passes_size_and_aspect_to_run_task(self):
        from llm_cli.batch import run_batch

        captured = {}

        def fake_create_client(mode, explicit_model=None):
            return object(), "test-image-model", {"BASE_URL": "https://example.com/v1"}

        def fake_run_task(mode, client, model, **kwargs):
            captured["image_size"] = kwargs["image_size"]
            captured["image_aspect_ratio"] = kwargs["image_aspect_ratio"]
            return {"mode": mode, "output_paths": ["/tmp/hero.jpg"], "printed": False}

        yaml_content = """\
mode: image
tasks:
  - id: hero-image
    prompt: "生成横版海报"
    size: 2K
    aspect: "16:9"
    output: hero.jpg
"""

        with TemporaryDirectory() as tmp:
            yaml_path = Path(tmp) / "tasks.yaml"
            yaml_path.write_text(yaml_content, encoding="utf-8")
            with patch("llm_cli.batch.create_client", fake_create_client), patch("llm_cli.batch.run_task", fake_run_task):
                run_batch(str(yaml_path))

        self.assertEqual(captured["image_size"], "2K")
        self.assertEqual(captured["image_aspect_ratio"], "16:9")

    def test_batch_top_level_prompt_is_forwarded_to_chat_tasks(self):
        from llm_cli.batch import run_batch

        captured = {}

        def fake_create_client(mode, explicit_model=None):
            return object(), "test-chat-model", {"BASE_URL": "https://example.com/v1"}

        def fake_run_task(mode, client, model, **kwargs):
            captured["prompt"] = kwargs["prompt"]
            return {"mode": mode, "text": "ok", "printed": True}

        yaml_content = """\
mode: chat
prompt: "@instruction.md"
tasks:
  - id: chat-task
    reference:
      - "ref.md"
"""

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            yaml_path = tmp_path / "tasks.yaml"
            yaml_path.write_text(yaml_content, encoding="utf-8")
            (tmp_path / "instruction.md").write_text("顶层提示词", encoding="utf-8")
            (tmp_path / "ref.md").write_text("参考文件", encoding="utf-8")
            with patch("llm_cli.batch.create_client", fake_create_client), patch("llm_cli.batch.run_task", fake_run_task):
                run_batch(str(yaml_path))

        self.assertEqual(captured["prompt"], "@instruction.md")

    def test_batch_image_task_uses_mode_and_index_for_default_output_name(self):
        from llm_cli.batch import run_batch

        captured = {}

        def fake_create_client(mode, explicit_model=None):
            return object(), "test-image-model", {"BASE_URL": "https://example.com/v1"}

        def fake_run_task(mode, client, model, **kwargs):
            captured["output"] = kwargs["output"]
            return {"mode": mode, "output_paths": [kwargs["output"]], "printed": False}

        yaml_content = """\
mode: image
tasks:
  - prompt: "生成横版海报"
"""

        with TemporaryDirectory() as tmp:
            yaml_path = Path(tmp) / "tasks.yaml"
            yaml_path.write_text(yaml_content, encoding="utf-8")
            with patch("llm_cli.batch.create_client", fake_create_client), patch("llm_cli.batch.run_task", fake_run_task):
                run_batch(str(yaml_path))

        self.assertEqual(captured["output"], str((Path(tmp) / "gemini-output" / "image-1.jpg").resolve()))

    def test_batch_default_output_name_ignores_yaml_id_field(self):
        from llm_cli.batch import run_batch

        captured = {}

        def fake_create_client(mode, explicit_model=None):
            return object(), "test-video-model", {"BASE_URL": "https://example.com/v1"}

        def fake_run_task(mode, client, model, **kwargs):
            captured["output"] = kwargs["output"]
            return {"mode": mode, "output_paths": [kwargs["output"]], "task_id": "vid_123", "printed": False}

        yaml_content = """\
mode: video
tasks:
  - id: custom-name
    prompt: "生成产品视频"
"""

        with TemporaryDirectory() as tmp:
            yaml_path = Path(tmp) / "tasks.yaml"
            yaml_path.write_text(yaml_content, encoding="utf-8")
            with patch("llm_cli.batch.create_client", fake_create_client), patch("llm_cli.batch.run_task", fake_run_task):
                run_batch(str(yaml_path))

        self.assertEqual(captured["output"], str((Path(tmp) / "gemini-output" / "video-1.mp4").resolve()))

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
                if kwargs.get("stream_handler"):
                    kwargs["stream_handler"]("新回答")
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
        from llm_cli.config import resolve_mode_settings

        config = {
            "modes": {
                "chat": {"provider": "openai", "model": "chat-model"},
                "image": {"provider": "openai", "model": "image-model"},
                "audio": {"provider": "openai", "model": "audio-model"},
            },
            "providers": {
                "openai": {
                    "base_url": "https://example.com/v1",
                    "api_key": "demo-key",
                }
            },
        }

        self.assertEqual(resolve_mode_settings("chat", config)["model"], "chat-model")
        self.assertEqual(resolve_mode_settings("text", config)["model"], "chat-model")
        self.assertEqual(resolve_mode_settings("image", config)["model"], "image-model")
        self.assertEqual(resolve_mode_settings("audio", config)["model"], "audio-model")

    def test_resolve_model_falls_back_to_global_model(self):
        from llm_cli.config import resolve_mode_settings

        config = {
            "default_provider": "shared",
            "default_model": "global-model",
            "providers": {
                "shared": {
                    "base_url": "https://example.com/v1",
                    "api_key": "demo-key",
                }
            },
        }

        self.assertEqual(resolve_mode_settings("chat", config)["model"], "global-model")
        self.assertEqual(resolve_mode_settings("image", config)["model"], "global-model")
        self.assertEqual(resolve_mode_settings("audio", config)["model"], "global-model")

    def test_load_runtime_config_uses_new_default_paths_and_expands_env_placeholders(self):
        from llm_cli.config import load_runtime_config

        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            config_dir = home / ".llm"
            config_dir.mkdir(parents=True)
            (config_dir / ".env").write_text("TEST_API_KEY=from-dot-env\n", encoding="utf-8")
            (config_dir / "config.yaml").write_text(
                """
default_provider: openai
modes:
  chat:
    model: chat-default
providers:
  openai:
    base_url: https://example.com/v1
    api_key: ${TEST_API_KEY}
    modes:
      chat:
        concurrency: 6
""".strip()
                + "\n",
                encoding="utf-8",
            )

            with patch("pathlib.Path.home", return_value=home), patch.dict(os.environ, {}, clear=True):
                runtime = load_runtime_config()

        self.assertEqual(runtime["paths"]["env_file"], config_dir / ".env")
        self.assertEqual(runtime["paths"]["config_file"], config_dir / "config.yaml")
        self.assertEqual(runtime["providers"]["openai"]["api_key"], "from-dot-env")
        self.assertEqual(runtime["modes"]["chat"]["model"], "chat-default")

    def test_load_runtime_config_prefers_runtime_environment_over_dot_env(self):
        from llm_cli.config import load_runtime_config

        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            config_dir = home / ".llm"
            config_dir.mkdir(parents=True)
            (config_dir / ".env").write_text("TEST_API_KEY=from-dot-env\n", encoding="utf-8")
            (config_dir / "config.yaml").write_text(
                """
default_provider: openai
providers:
  openai:
    base_url: https://example.com/v1
    api_key: ${TEST_API_KEY}
""".strip()
                + "\n",
                encoding="utf-8",
            )

            with patch("pathlib.Path.home", return_value=home), patch.dict(os.environ, {"TEST_API_KEY": "from-runtime"}, clear=True):
                runtime = load_runtime_config()

        self.assertEqual(runtime["providers"]["openai"]["api_key"], "from-runtime")

    def test_resolve_mode_settings_prefers_runtime_env_over_yaml_defaults(self):
        from llm_cli.config import load_runtime_config, resolve_mode_settings

        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            config_dir = home / ".llm"
            config_dir.mkdir(parents=True)
            (config_dir / ".env").write_text("", encoding="utf-8")
            (config_dir / "config.yaml").write_text(
                """
default_provider: cpa
modes:
  chat:
    provider: cpa
    model: gemini-3.1-pro
providers:
  cpa:
    base_url: https://cliproxy.jjcc.fun/v1
    api_key: cliproxy-key
    models:
      antigravity/gemini-3.1-pro-high:
        type: chat
        alias: gemini-3.1-pro
""".strip()
                + "\n",
                encoding="utf-8",
            )

            with patch("pathlib.Path.home", return_value=home), patch.dict(
                os.environ,
                {
                    "BASE_URL": "https://supercodex.space/v1",
                    "API_KEY": "runtime-key",
                    "CHAT_MODEL": "gpt-5.4",
                },
                clear=True,
            ):
                runtime = load_runtime_config()
                resolved = resolve_mode_settings("chat", runtime)

        self.assertEqual(resolved["provider"]["base_url"], "https://supercodex.space/v1")
        self.assertEqual(resolved["provider"]["api_key"], "runtime-key")
        self.assertEqual(resolved["model"], "gpt-5.4")

    def test_create_client_resolves_provider_protocol_and_explicit_model_alias(self):
        from llm_cli.config import create_client

        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            config_dir = home / ".llm"
            config_dir.mkdir(parents=True)
            (config_dir / ".env").write_text("VIDEO_KEY=test-video-key\n", encoding="utf-8")
            (config_dir / "config.yaml").write_text(
                """
default_provider: text-provider
modes:
  chat:
    provider: text-provider
    model: text-chat-model
  video:
    provider: reverse-video
    model: sora_t2v_turbo
providers:
  text-provider:
    base_url: https://text.example.com/v1
    api_key: text-key
    models:
      text-chat-model:
        type: chat
        alias: chat-default
  reverse-video:
    base_url: https://video.example.com/v1
    api_key: ${VIDEO_KEY}
    models:
      sora_t2v_turbo:
        type: video
        alias: sora-fast
        protocol: unified-video
      sora_t2v_pro:
        type: video
        alias: sora-pro
        protocol: unified-video
""".strip()
                + "\n",
                encoding="utf-8",
            )

            captured = {}

            def fake_openai(api_key=None, base_url=None):
                captured["api_key"] = api_key
                captured["base_url"] = base_url
                return SimpleNamespace(api_key=api_key, base_url=base_url)

            with patch("pathlib.Path.home", return_value=home), patch("llm_cli.config.OpenAI", fake_openai):
                client, model, config = create_client("video", explicit_model="sora-pro")

        self.assertEqual(model, "sora_t2v_pro")
        self.assertEqual(captured["api_key"], "test-video-key")
        self.assertEqual(captured["base_url"], "https://video.example.com/v1")
        self.assertEqual(config["provider"]["name"], "reverse-video")
        self.assertEqual(config["mode"]["protocol"], "unified-video")

    def test_resolve_mode_settings_attaches_named_reference_transport(self):
        from llm_cli.config import resolve_mode_settings

        config = {
            "default_provider": "reverse-video",
            "reference_transports": {
                "aliyun-s3": {
                    "endpoint": "https://oss.example.com",
                    "bucket": "demo-bucket",
                    "region": "cn-hangzhou",
                    "access_key_id": "ak",
                    "secret_access_key": "sk",
                    "public_base_url": "https://cdn.example.com",
                }
            },
            "providers": {
                "reverse-video": {
                    "base_url": "https://video.example.com/v1",
                    "api_key": "video-key",
                    "models": {
                        "video-model": {
                            "type": "video",
                            "alias": "video-default",
                            "reference_transport": "aliyun-s3",
                        }
                    },
                }
            },
            "modes": {
                "video": {"provider": "reverse-video", "model": "video-model"},
            },
        }

        settings = resolve_mode_settings("video", config)

        self.assertEqual(settings["mode"]["reference_transport"], "aliyun-s3")
        self.assertEqual(settings["reference_transport"]["bucket"], "demo-bucket")

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

    def test_finalize_image_round_persists_output_path_message(self):
        from llm_cli.interactive import InteractiveChatState, finalize_image_round

        with TemporaryDirectory() as tmp:
            session_path = Path(tmp) / "image.jsonl"
            history_messages = []
            state = InteractiveChatState(
                model="test-model",
                session_path=session_path,
                history_messages=[],
            )
            state.begin_assistant_response()
            state.finish_assistant_response()

            finalize_image_round(
                state=state,
                history_messages=history_messages,
                user_text="画一只猫",
                output_paths=["/tmp/cat.jpg"],
            )

            self.assertEqual(
                history_messages,
                [
                    {"role": "user", "content": "画一只猫", "meta": {"started_at": None}},
                    {"role": "system", "content": "已写入图片: /tmp/cat.jpg"},
                ],
            )

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
        file_parts = [part for part in content if part["type"] == "file"]
        text_parts = [part for part in content if part["type"] == "text"]
        self.assertEqual(len(file_parts), 2)
        self.assertEqual(file_parts[0]["file"]["filename"], "first.jpg")
        self.assertEqual(file_parts[1]["file"]["filename"], "second.jpg")
        self.assertEqual(text_parts, [{"type": "text", "text": "测试提示词"}])

    def test_build_messages_merges_image_prompt_and_input_text(self):
        from llm_cli.messages import build_messages

        messages = build_messages("image", prompt="主要求", input_text="补充约束")

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["role"], "user")
        self.assertEqual(messages[0]["content"], "主要求\n\n补充约束")

    def test_video_command_passes_creation_args_to_run_task(self):
        captured = {}

        def fake_create_client(mode, explicit_model=None):
            return object(), "test-video-model", {}

        def fake_run_task(mode, client, model, **kwargs):
            captured.update(kwargs)
            return {"mode": mode, "output_paths": ["/tmp/result.mp4"], "task_id": "vid_123", "printed": False}

        runner = CliRunner()
        with patch("llm_cli.cli.create_client", fake_create_client), patch("llm_cli.cli.run_task", fake_run_task):
            result = runner.invoke(
                cli,
                ["video", "生成测试视频", "-r", "cover.jpg", "--seconds", "8", "--size", "720x1280", "-o", "demo.mp4"],
            )

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(captured["prompt"], "生成测试视频")
        self.assertEqual(captured["reference"], ("cover.jpg",))
        self.assertEqual(captured["video_seconds"], "8")
        self.assertEqual(captured["video_size"], "720x1280")

    def test_video_command_accepts_arbitrary_size_and_seconds_values(self):
        captured = {}

        def fake_create_client(mode, explicit_model=None):
            return object(), "test-video-model", {}

        def fake_run_task(mode, client, model, **kwargs):
            captured["video_seconds"] = kwargs["video_seconds"]
            captured["video_size"] = kwargs["video_size"]
            return {"mode": mode, "output_paths": ["/tmp/result.mp4"], "task_id": "vid_123", "printed": False}

        runner = CliRunner()
        with patch("llm_cli.cli.create_client", fake_create_client), patch("llm_cli.cli.run_task", fake_run_task):
            result = runner.invoke(cli, ["video", "生成测试视频", "--seconds", "10", "--size", "1080P"])

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(captured["video_seconds"], "10")
        self.assertEqual(captured["video_size"], "1080P")

    def test_video_command_passes_resume_id_to_run_task(self):
        captured = {}

        def fake_create_client(mode, explicit_model=None):
            return object(), "test-video-model", {}

        def fake_run_task(mode, client, model, **kwargs):
            captured.update(kwargs)
            return {"mode": mode, "output_paths": ["/tmp/result.mp4"], "task_id": "vid_123", "printed": False}

        runner = CliRunner()
        with patch("llm_cli.cli.create_client", fake_create_client), patch("llm_cli.cli.run_task", fake_run_task):
            result = runner.invoke(cli, ["video", "--resume", "vid_123"])

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(captured["resume_task_id"], "vid_123")
        self.assertIsNone(captured["prompt"])

    def test_resolve_mode_settings_prefers_video_mode_over_global_default(self):
        from llm_cli.config import resolve_mode_settings

        config = {
            "default_provider": "shared",
            "default_model": "global-model",
            "modes": {
                "video": {"provider": "video-provider", "model": "video-model"},
            },
            "providers": {
                "shared": {
                    "base_url": "https://example.com/v1",
                    "api_key": "shared-key",
                    "models": {"global-model": {"type": "chat"}},
                },
                "video-provider": {
                    "base_url": "https://video.example.com/v1",
                    "api_key": "video-key",
                    "models": {"video-model": {"type": "video"}},
                },
            },
        }

        settings = resolve_mode_settings("video", config)

        self.assertEqual(settings["model"], "video-model")
        self.assertEqual(settings["provider"]["name"], "video-provider")

    def test_resolve_mode_settings_accepts_explicit_model_alias_from_provider_models(self):
        from llm_cli.config import resolve_mode_settings

        config = {
            "modes": {
                "video": {"provider": "reverse-video", "model": "sora_t2v_turbo"},
            },
            "providers": {
                "reverse-video": {
                    "base_url": "https://video.example.com/v1",
                    "api_key": "video-key",
                    "models": {
                        "sora_t2v_turbo": {"type": "video", "alias": "sora-fast"},
                        "sora_t2v_pro": {"type": "video", "alias": "sora-pro"},
                    },
                }
            },
        }

        settings = resolve_mode_settings("video", config, explicit_model="sora-pro")

        self.assertEqual(settings["model"], "sora_t2v_pro")
        self.assertEqual(settings["model_config"]["alias"], "sora-pro")

    def test_resolve_mode_settings_allows_undefined_explicit_model_on_selected_provider(self):
        from llm_cli.config import resolve_mode_settings

        config = {
            "modes": {
                "chat": {"provider": "cpa", "model": "default-chat-model"},
            },
            "providers": {
                "cpa": {
                    "base_url": "https://example.com/v1",
                    "api_key": "demo-key",
                    "models": {
                        "default-chat-model": {
                            "type": "chat",
                            "alias": "chat-default",
                        }
                    },
                }
            },
        }

        settings = resolve_mode_settings("chat", config, explicit_model="foxa/sonnet-4-5-202500929")

        self.assertEqual(settings["provider"]["name"], "cpa")
        self.assertEqual(settings["model"], "foxa/sonnet-4-5-202500929")
        self.assertIsNone(settings["model_config"])
        self.assertEqual(settings["mode"]["protocol"], "openai_chat")

    def test_run_task_video_resumes_until_completion_and_downloads(self):
        from llm_cli.task import run_task

        created = []
        polled = []
        downloaded = []

        def fake_create_video_task(client, **kwargs):
            created.append(kwargs)
            return {"id": "vid_123", "status": "queued"}

        poll_responses = iter(
            [
                {"id": "vid_123", "status": "processing"},
                {
                    "id": "vid_123",
                    "status": "succeeded",
                    "video_url": "https://example.com/files/vid_123.mp4",
                },
            ]
        )

        def fake_get_video_task(client, task_id):
            polled.append(task_id)
            return next(poll_responses)

        def fake_extract_video_result(task, output_path, task_id=None, progress_callback=None):
            downloaded.append((task, output_path, task_id))
            return ["/tmp/result.mp4"]

        with patch("llm_cli.task.create_video_task", fake_create_video_task), patch(
            "llm_cli.task.get_video_task", fake_get_video_task
        ), patch("llm_cli.task.extract_video_result", fake_extract_video_result), patch("llm_cli.task.time.sleep", lambda *_: None):
            result = run_task(
                "video",
                object(),
                "test-video-model",
                prompt="生成视频",
                reference="cover.jpg",
                video_seconds="8",
                video_size="720x1280",
                output="/tmp/out.mp4",
            )

        self.assertEqual(created[0]["prompt"], "生成视频")
        self.assertEqual(created[0]["seconds"], "8")
        self.assertEqual(created[0]["size"], "720x1280")
        self.assertEqual(polled, ["vid_123", "vid_123"])
        self.assertEqual(downloaded[0][1], "/tmp/out.mp4")
        self.assertEqual(downloaded[0][2], "vid_123")
        self.assertEqual(result["task_id"], "vid_123")
        self.assertEqual(result["output_paths"], ["/tmp/result.mp4"])

    def test_run_task_video_uses_staged_poll_schedule(self):
        from llm_cli.task import _video_poll_delay

        self.assertEqual(_video_poll_delay(0), 30)
        self.assertEqual(_video_poll_delay(299), 30)
        self.assertEqual(_video_poll_delay(300), 60)
        self.assertEqual(_video_poll_delay(1200), 60)

    def test_run_task_video_resume_still_waits_before_first_query(self):
        from llm_cli.task import run_task

        sleeps = []

        def fake_get_video_task(client, task_id):
            return {"id": task_id, "status": "succeeded"}

        def fake_extract_video_result(task, output_path, task_id=None, progress_callback=None):
            return ["/tmp/result.mp4"]

        with patch("llm_cli.task.get_video_task", fake_get_video_task), patch(
            "llm_cli.task.extract_video_result", fake_extract_video_result
        ), patch("llm_cli.task.time.sleep", lambda seconds: sleeps.append(seconds)):
            run_task(
                "video",
                object(),
                "test-video-model",
                resume_task_id="vid_123",
                output="/tmp/out.mp4",
            )

        self.assertEqual(sleeps, [30])

    def test_run_task_video_resume_skips_creation(self):
        from llm_cli.task import run_task

        downloaded = []

        def fake_get_video_task(client, task_id):
            return {"id": task_id, "status": "succeeded", "video_url": "https://example.com/files/vid_123.mp4"}

        def fake_extract_video_result(task, output_path, task_id=None, progress_callback=None):
            downloaded.append((task, output_path, task_id))
            return ["/tmp/result.mp4"]

        with patch("llm_cli.task.create_video_task") as create_mock, patch(
            "llm_cli.task.get_video_task", fake_get_video_task
        ), patch("llm_cli.task.extract_video_result", fake_extract_video_result):
            result = run_task(
                "video",
                object(),
                "test-video-model",
                resume_task_id="vid_123",
                output="/tmp/out.mp4",
            )

        create_mock.assert_not_called()
        self.assertEqual(downloaded[0][2], "vid_123")
        self.assertEqual(result["task_id"], "vid_123")

    def test_extract_video_result_uses_content_api_when_task_id_present(self):
        from llm_cli.output import extract_video_result

        client = object()

        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "video.mp4"
            with patch("llm_cli.output.download_video_content_stream", return_value=iter([b"mp4-bytes"])) as download_mock, patch(
                "llm_cli.output.urllib.request.urlopen"
            ) as urlopen_mock:
                paths = extract_video_result(
                    {
                        "_client": client,
                        "video_url": "https://example.com/video.mp4",
                    },
                    str(target),
                    task_id="vid_123",
                )

        download_mock.assert_called_once_with(client, "vid_123", config=None, task={"_client": client, "video_url": "https://example.com/video.mp4"})
        urlopen_mock.assert_not_called()
        self.assertEqual(paths, [str(target)])

    def test_create_video_task_uses_newapi_unified_protocol_payload(self):
        from llm_cli.api import create_video_task

        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"id":"task-1","status":"pending"}'

        def fake_urlopen(request, timeout=300):
            captured["url"] = request.full_url
            captured["content_type"] = request.headers["Content-type"]
            captured["body"] = request.data.decode("utf-8")
            return FakeResponse()

        client = SimpleNamespace(base_url="https://video.example.com/v1", api_key="demo-key")
        config = {
            "mode": {
                "protocol": "unified-video",
                "defaults": {"aspect_ratio": "16:9"},
            }
        }

        with TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "cover.jpg"
            image_path.write_bytes(b"fake-image")
            with patch("llm_cli.api.urllib.request.urlopen", fake_urlopen):
                result = create_video_task(
                    client,
                    model="sora-fast-real",
                    prompt="test prompt",
                    size="720p",
                    input_reference=str(image_path),
                    config=config,
                )

        self.assertEqual(result["id"], "task-1")
        self.assertEqual(captured["url"], "https://video.example.com/v1/video/create")
        self.assertEqual(captured["content_type"], "application/json")
        self.assertIn('"aspect_ratio": "16:9"', captured["body"])
        self.assertIn('"size": "720p"', captured["body"])
        self.assertIn('"images": ["data:image/jpeg;base64,', captured["body"])

    def test_prepare_reference_resources_uploads_files_to_named_transport(self):
        from llm_cli.reference_transport import prepare_reference_resources

        uploads = []

        class FakeClient:
            def put_object(self, Bucket=None, Key=None, Body=None, ContentType=None):
                uploads.append((Bucket, Key, Body, ContentType))

        config = {
            "mode": {
                "reference_transport": "aliyun-s3",
            },
            "reference_transports": {
                "aliyun-s3": {
                    "endpoint": "https://oss.example.com",
                    "bucket": "demo-bucket",
                    "region": "cn-hangzhou",
                    "access_key_id": "ak",
                    "secret_access_key": "sk",
                    "public_base_url": "https://cdn.example.com/assets",
                    "key_prefix": "llmcmd",
                }
            },
        }

        with TemporaryDirectory() as tmp:
            first = Path(tmp) / "first.png"
            second = Path(tmp) / "second.jpg"
            first.write_bytes(b"one")
            second.write_bytes(b"two")
            with patch("llm_cli.reference_transport.create_s3_client", return_value=FakeClient()), patch(
                "llm_cli.reference_transport.time_ns",
                side_effect=[1111111111111111111, 2222222222222222222],
            ), patch(
                "llm_cli.reference_transport.uuid4",
                side_effect=[
                    SimpleNamespace(hex="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"),
                    SimpleNamespace(hex="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"),
                ],
            ):
                result = prepare_reference_resources([str(first), str(second)], config=config)

        self.assertEqual(result["local_paths"], [str(first), str(second)])
        self.assertEqual(
            result["url_references"],
            [
                "https://cdn.example.com/assets/llmcmd/1111111111111111111-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png",
                "https://cdn.example.com/assets/llmcmd/2222222222222222222-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.jpg",
            ],
        )
        self.assertEqual(uploads[0][0], "demo-bucket")
        self.assertEqual(uploads[0][1], "llmcmd/1111111111111111111-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png")
        self.assertEqual(uploads[0][2], b"one")
        self.assertEqual(uploads[0][3], "image/png")
        self.assertEqual(uploads[1][1], "llmcmd/2222222222222222222-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.jpg")
        self.assertEqual(uploads[1][2], b"two")
        self.assertEqual(uploads[1][3], "image/jpeg")

    def test_prepare_reference_resources_without_transport_preserves_only_local_paths(self):
        from llm_cli.reference_transport import prepare_reference_resources

        result = prepare_reference_resources(["/tmp/a.png"], config={"mode": {}}, base_dir=None)

        self.assertEqual(result["local_paths"], ["/tmp/a.png"])
        self.assertEqual(result["url_references"], [])

    def test_prepare_reference_resources_can_return_presigned_urls(self):
        from llm_cli import api as api_module
        from llm_cli.reference_transport import prepare_reference_resources

        uploads = []
        presign_calls = []

        class FakeClient:
            def put_object(self, Bucket=None, Key=None, Body=None, ContentType=None):
                uploads.append((Bucket, Key, Body, ContentType))

            def generate_presigned_url(self, operation_name, Params=None, ExpiresIn=None):
                presign_calls.append((operation_name, Params, ExpiresIn))
                return f"https://signed.example.com/{Params['Key']}?expires={ExpiresIn}"

        config = {
            "mode": {
                "reference_transport": "aliyun-s3",
            },
            "reference_transports": {
                "aliyun-s3": {
                    "endpoint": "https://oss.example.com",
                    "bucket": "demo-bucket",
                    "region": "cn-hangzhou",
                    "access_key_id": "ak",
                    "secret_access_key": "sk",
                    "url_mode": "presign",
                    "expires_in": 1800,
                    "key_prefix": "llmcmd",
                }
            },
        }

        stderr = StringIO()
        old_stderr = os.sys.stderr
        old_debug = api_module.DEBUG
        os.sys.stderr = stderr
        api_module.set_debug(True)

        try:
            with TemporaryDirectory() as tmp:
                image_path = Path(tmp) / "first.png"
                image_path.write_bytes(b"one")
                with patch("llm_cli.reference_transport.create_s3_client", return_value=FakeClient()), patch(
                    "llm_cli.reference_transport.time_ns",
                    return_value=1111111111111111111,
                ), patch(
                    "llm_cli.reference_transport.uuid4",
                    return_value=SimpleNamespace(hex="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"),
                ):
                    result = prepare_reference_resources([str(image_path)], config=config)
        finally:
            os.sys.stderr = old_stderr
            api_module.set_debug(old_debug)

        self.assertEqual(
            result["url_references"],
            ["https://signed.example.com/llmcmd/1111111111111111111-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png?expires=1800"],
        )
        self.assertEqual(presign_calls[0][0], "get_object")
        self.assertEqual(presign_calls[0][1]["Bucket"], "demo-bucket")
        self.assertEqual(presign_calls[0][1]["Key"], "llmcmd/1111111111111111111-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png")
        self.assertEqual(presign_calls[0][2], 1800)
        self.assertIn("参考资源上传开始:", stderr.getvalue())
        self.assertIn("参考资源签名 URL:", stderr.getvalue())

    def test_create_s3_client_uses_virtual_hosted_style(self):
        from llm_cli.reference_transport import create_s3_client

        captured = {}

        def fake_client(service_name, **kwargs):
            captured["service_name"] = service_name
            captured["kwargs"] = kwargs
            return object()

        with patch("llm_cli.reference_transport.boto3.client", fake_client):
            create_s3_client(
                {
                    "endpoint": "https://oss-cn-shenzhen.aliyuncs.com",
                    "region": "cn-shenzhen",
                    "access_key_id": "ak",
                    "secret_access_key": "sk",
                }
            )

        self.assertEqual(captured["service_name"], "s3")
        self.assertEqual(captured["kwargs"]["endpoint_url"], "https://oss-cn-shenzhen.aliyuncs.com")
        self.assertEqual(captured["kwargs"]["config"].s3["addressing_style"], "virtual")
        self.assertFalse(captured["kwargs"]["config"].s3["payload_signing_enabled"])
        self.assertEqual(captured["kwargs"]["config"].request_checksum_calculation, "when_required")

    def test_extract_video_result_streams_chunks_to_file(self):
        from llm_cli.output import extract_video_result

        class FakeStream:
            def __iter__(self):
                return iter([b"abc", b"def", b""])

        client = object()
        progress_events = []

        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "video.mp4"
            with patch("llm_cli.output.download_video_content_stream", return_value=FakeStream()):
                paths = extract_video_result(
                    {"_client": client},
                    str(target),
                    task_id="vid_123",
                    progress_callback=lambda event, **payload: progress_events.append((event, payload)),
                )
            self.assertEqual(target.read_bytes(), b"abcdef")

        self.assertEqual(paths, [str(target)])
        self.assertEqual(progress_events[0][0], "download_start")
        self.assertEqual(progress_events[-1][0], "download_done")

    def test_extract_video_result_uses_video_url_for_newapi_unified_protocol(self):
        from llm_cli.output import extract_video_result

        captured = {}

        class FakeResponse:
            headers = {}

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self, chunk_size):
                if not hasattr(self, "_chunks"):
                    self._chunks = iter([b"video-", b"bytes", b""])
                return next(self._chunks)

        def fake_urlopen(request, timeout=300):
            captured["url"] = request.full_url
            return FakeResponse()

        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "video.mp4"
            with patch("llm_cli.api.urllib.request.urlopen", fake_urlopen):
                paths = extract_video_result(
                    {
                        "_client": SimpleNamespace(base_url="https://video.example.com/v1", api_key="demo-key"),
                        "_config": {"mode": {"protocol": "unified-video"}},
                        "video_url": "https://cdn.example.com/video.mp4",
                    },
                    str(target),
                    task_id="task-1",
                )
            self.assertEqual(paths, [str(target)])
            self.assertEqual(captured["url"], "https://cdn.example.com/video.mp4")
            self.assertEqual(target.read_bytes(), b"video-bytes")

    def test_create_video_task_uses_uploaded_urls_for_newapi_unified_protocol(self):
        from llm_cli.api import create_video_task

        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"id":"task-1","status":"pending"}'

        def fake_urlopen(request, timeout=300):
            captured["body"] = request.data.decode("utf-8")
            return FakeResponse()

        client = SimpleNamespace(base_url="https://video.example.com/v1", api_key="demo-key")

        with patch("llm_cli.api.urllib.request.urlopen", fake_urlopen):
            create_video_task(
                client,
                model="sora-fast-real",
                prompt="test prompt",
                size="720p",
                config={"mode": {"protocol": "unified-video"}},
                reference_urls=["https://cdn.example.com/a.png", "https://cdn.example.com/b.png"],
            )

        self.assertIn('"images": ["https://cdn.example.com/a.png", "https://cdn.example.com/b.png"]', captured["body"])

    def test_run_task_video_accepts_task_id_field_from_create_response(self):
        from llm_cli.task import run_task

        def fake_create_video_task(client, **kwargs):
            return {"task_id": "vid_abc", "status": "queued"}

        def fake_get_video_task(client, task_id):
            return {"id": task_id, "status": "succeeded", "video_url": "https://example.com/files/vid_abc.mp4"}

        def fake_extract_video_result(task, output_path, task_id=None, progress_callback=None):
            return ["/tmp/result.mp4"]

        with patch("llm_cli.task.create_video_task", fake_create_video_task), patch(
            "llm_cli.task.get_video_task", fake_get_video_task
        ), patch("llm_cli.task.extract_video_result", fake_extract_video_result), patch("llm_cli.task.time.sleep", lambda *_: None):
            result = run_task(
                "video",
                object(),
                "test-video-model",
                prompt="生成视频",
                output="/tmp/out.mp4",
            )

        self.assertEqual(result["task_id"], "vid_abc")

    def test_batch_video_task_passes_seconds_and_size_to_run_task(self):
        from llm_cli.batch import run_batch

        captured = {}

        def fake_create_client(mode, explicit_model=None):
            return object(), "test-video-model", {"BASE_URL": "https://example.com/v1"}

        def fake_run_task(mode, client, model, **kwargs):
            captured["video_seconds"] = kwargs["video_seconds"]
            captured["video_size"] = kwargs["video_size"]
            captured["reference"] = kwargs["reference"]
            return {"mode": mode, "output_paths": ["/tmp/hero.mp4"], "task_id": "vid_123", "printed": False}

        yaml_content = """\
mode: video
tasks:
  - id: hero-video
    prompt: "生成横版产品视频"
    seconds: "8"
    size: 1280x720
    reference:
      - cover.jpg
    output: hero.mp4
"""

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            yaml_path = tmp_path / "tasks.yaml"
            yaml_path.write_text(yaml_content, encoding="utf-8")
            (tmp_path / "cover.jpg").write_bytes(b"fake")
            with patch("llm_cli.batch.create_client", fake_create_client), patch("llm_cli.batch.run_task", fake_run_task):
                run_batch(str(yaml_path))

        self.assertEqual(captured["video_seconds"], "8")
        self.assertEqual(captured["video_size"], "1280x720")
        self.assertEqual(captured["reference"], ["cover.jpg"])

    def test_batch_video_task_accepts_unrestricted_size_value(self):
        from llm_cli.batch import run_batch

        captured = {}

        def fake_create_client(mode, explicit_model=None):
            return object(), "test-video-model", {"BASE_URL": "https://example.com/v1"}

        def fake_run_task(mode, client, model, **kwargs):
            captured["video_size"] = kwargs["video_size"]
            return {"mode": mode, "output_paths": ["/tmp/hero.mp4"], "task_id": "vid_123", "printed": False}

        yaml_content = """\
mode: video
tasks:
  - id: hero-video
    prompt: "生成竖版产品视频"
    size: "1080P"
"""

        with TemporaryDirectory() as tmp:
            yaml_path = Path(tmp) / "tasks.yaml"
            yaml_path.write_text(yaml_content, encoding="utf-8")
            with patch("llm_cli.batch.create_client", fake_create_client), patch("llm_cli.batch.run_task", fake_run_task):
                run_batch(str(yaml_path))

        self.assertEqual(captured["video_size"], "1080P")


if __name__ == "__main__":
    unittest.main()
