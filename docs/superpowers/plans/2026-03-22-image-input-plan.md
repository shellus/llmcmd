# Image Input Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `llm image` 支持通过 `-i/--input` 传入文本约束文件，并和主 `prompt` 一起发给模型。

**Architecture:** 在 `cli.py` 为 `image` 子命令增加 `-i/--input` 参数，复用现有 `read_input_files` 和 `build_messages` 数据流，将文本输入聚合到 image 请求的文本部分。测试覆盖 CLI 透传和消息构造两个层面。

**Tech Stack:** Python 3, Click, unittest

---

### Task 1: 增加失败测试

**Files:**
- Modify: `tests/test_chat_session.py`

- [ ] **Step 1: 写失败测试**
- [ ] **Step 2: 运行定点测试确认失败**
- [ ] **Step 3: 实现最小代码**
- [ ] **Step 4: 重新运行定点测试确认通过**

### Task 2: 实现 image `-i` 输入

**Files:**
- Modify: `src/llm_cli/cli.py`
- Modify: `src/llm_cli/task.py`
- Modify: `src/llm_cli/messages.py`

- [ ] **Step 1: 为 image 增加 `-i/--input`**
- [ ] **Step 2: 把输入文件文本透传到 `run_task`**
- [ ] **Step 3: 让 image 请求拼入补充文本**
- [ ] **Step 4: 跑测试确认通过**

### Task 3: 更新文档

**Files:**
- Modify: `README.md`
- Modify: `SKILL.md`

- [ ] **Step 1: 更新 `image` 示例**
- [ ] **Step 2: 更新参数说明**
- [ ] **Step 3: 跑全量测试**
