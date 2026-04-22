import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch


class GptImage2ProtocolTests(unittest.TestCase):
    def test_sanitize_debug_value_truncates_openai_responses_image_fields(self):
        from llm_cli.api import sanitize_debug_value

        sanitized = sanitize_debug_value(
            {
                "input": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_image",
                                "image_url": "data:image/png;base64," + ("A" * 300),
                            }
                        ],
                    }
                ],
                "item": {
                    "type": "image_generation_call",
                    "result": "B" * 300,
                },
            },
            limit=50,
        )

        self.assertIn("...<truncated, total", sanitized["input"][0]["content"][0]["image_url"])
        self.assertIn("...<truncated, total", sanitized["item"]["result"])

    def test_api_call_uses_responses_sse_and_extracts_image_result(self):
        from llm_cli.api import api_call

        captured = {}
        sse_lines = [
            line.encode("utf-8")
            for line in [
                'event: response.output_text.done\n',
                'data: {"type":"response.output_text.done","text":"已生成图片"}\n',
                '\n',
                'event: response.output_item.done\n',
                'data: {"type":"response.output_item.done","item":{"type":"image_generation_call","status":"completed","result":"QUJD","revised_prompt":"猫抱着水獭"}}\n',
                '\n',
                'event: response.completed\n',
                'data: {"type":"response.completed"}\n',
                '\n',
                'data: [DONE]\n',
                '\n',
            ]
        ]

        class FakeResponse:
            status = 200
            headers = {"Content-Type": "text/event-stream"}

            def __init__(self, lines):
                self._lines = iter(lines)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def readline(self):
                return next(self._lines, b"")

        def fake_urlopen(request, timeout=300):
            captured["url"] = request.full_url
            captured["headers"] = dict(request.header_items())
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse(sse_lines)

        client = SimpleNamespace(base_url="https://example.com/v1", api_key="sk-test")
        messages = [{"role": "user", "content": "画一只可爱的猫抱着水獭"}]

        with patch("llm_cli.api.urllib.request.urlopen", fake_urlopen):
            response = api_call(
                client,
                "gpt-image-2",
                messages,
                config={"mode": {"protocol": "openai-responses"}},
            )

        self.assertEqual(captured["url"], "https://example.com/v1/responses")
        self.assertEqual(captured["body"]["model"], "gpt-image-2")
        self.assertTrue(captured["body"]["stream"])
        self.assertEqual(
            captured["body"]["input"],
            [{"role": "user", "content": [{"type": "input_text", "text": "画一只可爱的猫抱着水獭"}]}],
        )
        self.assertEqual(response.choices[0].message.content, "已生成图片")
        self.assertEqual(
            response.choices[0].message.images,
            [
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,QUJD"},
                    "revised_prompt": "猫抱着水獭",
                }
            ],
        )

    def test_api_call_converts_image_file_parts_to_responses_input_image(self):
        from llm_cli.api import api_call

        captured = {}

        class FakeResponse:
            status = 200
            headers = {"Content-Type": "text/event-stream"}

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def readline(self):
                return b""

        def fake_urlopen(request, timeout=300):
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse()

        client = SimpleNamespace(base_url="https://example.com/v1", api_key="sk-test")
        messages = [
            {
                "role": "system",
                "content": "只输出一张图",
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "file",
                        "file": {
                            "filename": "ref.png",
                            "mime_type": "image/png",
                            "file_data": "data:image/png;base64,QQ==",
                        },
                    },
                    {"type": "text", "text": "保留主体，改成像素风"},
                ],
            },
        ]

        with patch("llm_cli.api.urllib.request.urlopen", fake_urlopen):
            api_call(
                client,
                "gpt-image-2",
                messages,
                config={"mode": {"protocol": "openai-responses"}},
            )

        self.assertEqual(captured["body"]["instructions"], "只输出一张图")
        self.assertEqual(
            captured["body"]["input"],
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_image", "image_url": "data:image/png;base64,QQ=="},
                        {"type": "input_text", "text": "保留主体，改成像素风"},
                    ],
                }
            ],
        )

    def test_run_task_uses_png_default_output_for_openai_responses_image(self):
        from llm_cli.task import run_task

        response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="",
                        images=[{"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}}],
                        refusal=None,
                    )
                )
            ]
        )

        with TemporaryDirectory() as tmp:
            default_path = Path(tmp) / "output.jpg"
            with patch("llm_cli.task.api_call", lambda *args, **kwargs: response), patch(
                "llm_cli.task.default_output_path", return_value=str(default_path)
            ):
                result = run_task(
                    "image",
                    object(),
                    "gpt-image-2",
                    prompt="画一只猫",
                    config={"mode": {"protocol": "openai-responses"}},
                )

        self.assertEqual(result["mode"], "image")
        self.assertEqual(result["output_paths"], [str(default_path.with_suffix(".png"))])
