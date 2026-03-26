# Video Command Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `shellus-llmcmd` 增加 `llm video`，支持创建异步视频任务、等待完成并自动下载，以及按任务 ID 恢复等待下载。

**Architecture:** 在现有 `chat/image/audio` 命令分层之外新增 `video` 模式，但不复用 `chat.completions.create` 协议。CLI 负责参数解析，`task.py` 编排创建/恢复/轮询/下载，`api.py` 负责视频相关 HTTP 调用，`output.py` 负责视频文件落盘，配置层新增 `VIDEO_MODEL` 解析。

**Tech Stack:** Python 3.10+, Click, OpenAI-compatible config loading, urllib, unittest

---

### Task 1: 覆盖 CLI 与配置入口

**Files:**
- Modify: `src/llm_cli/cli.py`
- Modify: `src/llm_cli/config.py`
- Modify: `src/llm_cli/utils.py`
- Test: `tests/test_chat_session.py`

- [ ] **Step 1: 写出失败测试**
- [ ] **Step 2: 运行对应测试并确认失败**
- [ ] **Step 3: 最小实现 `video` 命令参数与 `VIDEO_MODEL` 解析**
- [ ] **Step 4: 重新运行测试并确认通过**

### Task 2: 覆盖视频 API 编排与结果下载

**Files:**
- Modify: `src/llm_cli/api.py`
- Modify: `src/llm_cli/task.py`
- Modify: `src/llm_cli/output.py`
- Test: `tests/test_chat_session.py`

- [ ] **Step 1: 写出失败测试**
- [ ] **Step 2: 运行对应测试并确认失败**
- [ ] **Step 3: 实现视频任务创建、轮询状态、结果下载与 `--resume` 路径**
- [ ] **Step 4: 重新运行测试并确认通过**

### Task 3: 覆盖文档与批处理边界

**Files:**
- Modify: `README.md`
- Modify: `src/llm_cli/batch.py`
- Test: `tests/test_chat_session.py`

- [ ] **Step 1: 写出失败测试**
- [ ] **Step 2: 运行对应测试并确认失败**
- [ ] **Step 3: 实现 `batch` 的 `video` 支持并更新 README 使用说明**
- [ ] **Step 4: 运行相关测试并确认通过**
