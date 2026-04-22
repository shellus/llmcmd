# Chat Video Input Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `llm chat -r` 增加视频附件理解输入，让通用 Gemini 多模态理解模型能够直接接收本地视频文件，而不是要求人工拆帧。

**Architecture:** 第一阶段只扩展 `chat` 模式，不改动 `llm video` 的视频生成链路。实现路径沿用现有附件分层：`files.py` 负责视频 MIME 识别，`messages.py` 负责把视频构造成 OpenAI 风格 `file` 内容块，`task.py` 继续复用已有 `reference` 流程，测试覆盖 CLI 透传、附件识别与消息构造。能力依据与请求格式依据已经写入 `docs/模型能力和请求方式/`。

**Tech Stack:** Python 3.10+, Click, unittest, OpenAI-compatible chat payloads

---

### Task 1: 补齐视频附件识别

**Files:**
- Modify: `src/llm_cli/files.py`
- Test: `tests/test_chat_session.py`

- [ ] **Step 1: 写失败测试，约束视频附件识别结果**

```python
def test_detect_mime_type_supports_video_mp4_and_mov(self):
    from llm_cli.files import detect_mime_type

    self.assertEqual(detect_mime_type("demo.mp4", expected_kind="video"), "video/mp4")
    self.assertEqual(detect_mime_type("demo.mov", expected_kind="video"), "video/quicktime")
```

- [ ] **Step 2: 运行定点测试确认失败**

Run: `pytest tests/test_chat_session.py -k "video_mp4_and_mov" -v`
Expected: FAIL，提示 `expected_kind="video"` 尚未支持

- [ ] **Step 3: 在 `files.py` 增加视频 MIME 识别与 `is_video_attachment()`**

实现要求：
- 复用 `detect_mime_type()` 分支结构
- `expected_kind="video"` 时要求 MIME 以 `video/` 开头
- 为常见扩展名补显式映射，至少覆盖 `mp4`、`mov`、`webm`、`avi`、`mkv`、`mpeg`、`mpg`
- 不改动现有图片、音频、文本逻辑

- [ ] **Step 4: 重新运行测试确认通过**

Run: `pytest tests/test_chat_session.py -k "video_mp4_and_mov" -v`
Expected: PASS

### Task 2: 为 `chat` 增加视频附件消息构造

**Files:**
- Modify: `src/llm_cli/messages.py`
- Test: `tests/test_chat_session.py`

- [ ] **Step 1: 写失败测试，约束 `chat` 模式接受视频附件**

```python
def test_build_messages_chat_accepts_video_file_reference(self):
    from llm_cli.messages import build_messages

    with patch("llm_cli.messages.load_binary_attachment") as mock_load, patch(
        "llm_cli.messages.is_video_attachment", return_value=True
    ), patch("llm_cli.messages.is_image_attachment", return_value=False), patch(
        "llm_cli.messages.is_audio_attachment", return_value=False
    ), patch("llm_cli.messages.is_text_attachment", return_value=False):
        mock_load.return_value = {
            "path": "/tmp/demo.mp4",
            "mime_type": "video/mp4",
            "base64_data": "QQ==",
        }
        messages = build_messages("chat", prompt="总结这个视频", reference_path=["/tmp/demo.mp4"])

    content = messages[0]["content"]
    assert content[1]["type"] == "file"
    assert content[1]["file"]["mime_type"] == "video/mp4"
```

- [ ] **Step 2: 运行定点测试确认失败**

Run: `pytest tests/test_chat_session.py -k "chat_accepts_video_file_reference" -v`
Expected: FAIL，提示 `chat 模式暂不支持该附件类型`

- [ ] **Step 3: 在 `messages.py` 中按现有音频文件路径接入视频附件**

实现要求：
- 引入 `is_video_attachment`
- `chat` 模式遇到视频附件时，复用 `_build_file_part(path, expected_kind="video")`
- 保持图片仍走 `image_url`
- 保持音频仍走 `file`
- 保持文本仍走内联 `text`
- `chat_edit` 第一阶段不支持视频
- `image` 第一阶段不支持视频

- [ ] **Step 4: 重新运行相关测试确认通过**

Run: `pytest tests/test_chat_session.py -k "chat_accepts_video_file_reference or chat_accepts_audio_file_reference" -v`
Expected: PASS

### Task 3: 补充请求与文档边界测试

**Files:**
- Modify: `tests/test_chat_session.py`
- Modify: `README.md`
- Modify: `SKILL.md`
- Modify: `docs/模型能力和请求方式/llmcmd-附件提交方式.md`

- [ ] **Step 1: 写失败测试，约束不支持路径仍然报错**

```python
def test_build_messages_chat_edit_rejects_video_reference(self):
    from llm_cli.messages import build_messages

    with patch("llm_cli.messages.is_video_attachment", return_value=True), patch(
        "llm_cli.messages.is_image_attachment", return_value=False
    ), patch("llm_cli.messages.is_text_attachment", return_value=False):
        with self.assertRaises(SystemExit):
            build_messages("chat_edit", prompt="改写", input_text="原文", reference_path=["/tmp/demo.mp4"])
```

- [ ] **Step 2: 运行定点测试确认失败**

Run: `pytest tests/test_chat_session.py -k "chat_edit_rejects_video_reference" -v`
Expected: FAIL，说明当前边界未被显式约束

- [ ] **Step 3: 更新文档**

文档要求：
- `README.md` 增加 `llm chat "总结这个视频" -r demo.mp4` 示例
- `SKILL.md` 同步增加相同能力说明
- `docs/模型能力和请求方式/llmcmd-附件提交方式.md` 增补新的视频附件提交格式
- 明确第一阶段仅支持 `chat -r` 视频理解，不支持 `chat --edit` 和 `image -r` 视频输入

- [ ] **Step 4: 跑相关测试并确认通过**

Run: `pytest tests/test_chat_session.py -k "video_reference or audio_file_reference or build_messages_chat" -v`
Expected: PASS

### Task 4: 全量回归与提交准备

**Files:**
- Modify: `docs/dev-spec/llm-cli技术设计.md`
- Verify: `git diff`
- Verify: `git status`

- [ ] **Step 1: 清理已发现的文档失配**

要求：
- 修正 `docs/dev-spec/llm-cli技术设计.md` 中残留的 `audio` 子命令旧表述
- 修正旧配置路径 `~/.config/llm-api/.env`
- 保持与 `README.md`、`DEVELOPING.md`、当前实现一致

- [ ] **Step 2: 跑回归测试**

Run: `pytest tests/test_chat_session.py -v`
Expected: PASS

- [ ] **Step 3: 检查改动**

Run:

```bash
git status --short
git diff -- README.md SKILL.md docs/模型能力和请求方式 src/llm_cli tests/test_chat_session.py
```

Expected: 只包含视频输入支持与相关文档同步

- [ ] **Step 4: 提交**

```bash
git add README.md SKILL.md docs/模型能力和请求方式 docs/dev-spec/llm-cli技术设计.md src/llm_cli/files.py src/llm_cli/messages.py tests/test_chat_session.py
git commit -m "feat: 为 chat 引入视频附件理解输入"
```
