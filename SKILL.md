---
name: llmcmd
description: Use when handling terminal-first LLM workflows for text generation, image generation, audio transcription, YAML batch tasks, or file-based prompt and reference inputs.
---

# llmcmd

## Overview

`llmcmd` 是一个终端优先的统一 LLM 命令行技能，核心入口是 `llm`。

适用目标：

- 用 `chat` 处理生成、总结、改写、结构化提取
- 用 `image` 生成或编辑图片
- 用 `audio` 转写、总结或产出字幕
- 用 `batch` 通过 YAML 批量编排任务
- 用 `chat --edit` 基于要求直接修改文本文件

## When to Use

在以下场景使用本技能：

- 需要把 AI 能力嵌入 shell、脚本、自动化流程或 CI
- 需要一次性读取本地文本、图片、文档、音频作为参考输入
- 需要把多步任务收敛到单个 CLI，而不是切换多个网页或客户端
- 需要持久化会话，在终端中继续同一轮对话
- 需要批量执行多条 prompt 任务并写出结构化结果

以下情况不适合：

- 只是在网页里做一次普通聊天，不需要命令行集成
- 任务依赖复杂交互界面，而不是文件、参数和标准输出

## Quick Reference

### 安装

```bash
pip install shellus-llmcmd
```

命令名：

```bash
llm
```

### 四种模式

| 模式 | 用途 | 常用输入 | 常用输出 |
|------|------|----------|----------|
| `llm chat` | 文本生成、分析、问答、改写、编辑文件 | prompt、`@文件`、`-r` 附件 | stdout、文件、会话 |
| `llm image` | 图片生成、参考图编辑 | prompt、`@文件`、`-r` 附件 | 图片文件 |
| `llm audio` | 音频转写、总结、字幕 | prompt、音频附件 | stdout、字幕文件 |
| `llm batch` | YAML 批量任务 | `tasks.yaml` | 输出目录内多个结果 |

## Core Patterns

### 1. 文本任务

```bash
llm chat "总结重点"
llm chat @prompt.txt -o result.md
llm chat "总结这个附件" -r report.pdf
```

规则：

- `@文件` 会把文本直接读入 prompt
- `-r/--reference` 用于传入图片、文档、音频等参考附件
- `-o` 用于写出结果；不写时默认输出到 stdout

### 2. 直接编辑文件

```bash
llm chat "把语气改得更专业，但不要改变原意" --edit prompt.md
llm chat "按要求改写" --edit prompt.md -o prompt.v2.md
```

适用场景：

- 改写提示词
- 修正文案
- 在保留原结构的前提下局部调整文本

### 3. 图片生成与参考图编辑

```bash
llm image "生成三张海报方案" -n 3 -o poster.jpg
llm image "融合两张参考图的风格生成图片" -r person.jpg -r style.jpg -o result.jpg
llm image @prompt.md -r ref.jpg -o output.jpg
```

补充参数：

- `-n/--count` 控制生成数量
- `--size` 支持 `512 / 1K / 2K / 4K`
- `--aspect` 支持 `1:1 / 16:9 / 9:16 / 4:3 / 3:4 / 3:2 / 2:3 / 4:5 / 5:4 / 21:9`

### 4. 音频处理

```bash
llm audio -r demo.m4a
llm audio "总结录音内容" -r demo.m4a
llm audio "请输出标准 SRT 字幕" -r demo.m4a -o demo.srt
```

说明：

- 不提供 prompt 时，可直接做默认转写
- 需要字幕时，应在 prompt 中明确要求输出格式

### 5. 会话持久化

```bash
llm chat "继续上次讨论" -s worklog
llm chat -I -s worklog
llm chat -I "你是什么模型？"
```

说明：

- `-s/--session` 读取并持久化会话
- `-I/--interactive` 进入交互式连续对话
- `-I` 只有搭配 `-s` 才会回放并写回历史

内置命令：

- `/clear`
- `/model <name>`
- `/save <name-or-path>`

### 6. YAML 批处理

```bash
llm batch tasks.yaml
```

示例：

```yaml
mode: chat
system_prompt: "你是严谨的处理助手"
output_dir: outputs

tasks:
  - id: summary
    prompt: "总结下面内容"
    input: article.md
    output: summary.md

  - id: hero-image
    mode: image
    prompt: "为产品主页生成三张极简横幅图"
    count: 3
    size: 2K
    aspect: "16:9"
    output: hero.jpg
```

## Configuration

默认配置文件位置：

```bash
~/.config/llm-api/.env
```

最小配置：

```bash
API_KEY=your_api_key
BASE_URL=https://your-api-endpoint/v1
MODEL=your_default_model
```

按能力拆分模型：

```bash
CHAT_MODEL=your_chat_model
IMAGE_MODEL=your_image_model
AUDIO_MODEL=your_audio_model
```

并发配置：

```bash
LLM_CONCURRENCY=4
OPENAI_CHAT_CONCURRENCY=4
OPENAI_IMAGE_CONCURRENCY=4
```

模型选择顺序：

- `chat`：`CHAT_MODEL` -> `MODEL`
- `image`：`IMAGE_MODEL` -> `MODEL`
- `audio`：`AUDIO_MODEL` -> `MODEL`

## Common Mistakes

- 把适合 `@文件` 的长文本直接硬编码到命令里，导致命令难维护
- 需要多轮对话却没用 `-s`，导致上下文无法复用
- 在 YAML 里把 `aspect` 写成未加引号的 `16:9`，被 YAML 误解析
- 期待 `audio` 自动输出 SRT，但 prompt 没明确要求字幕格式
- 将环境域名、密钥、账号写入受版本控制文件，而不是放进 `.env`

## Package Info

- PyPI 包名：`shellus-llmcmd`
- CLI 命令名：`llm`
- Python 要求：`>=3.10`
