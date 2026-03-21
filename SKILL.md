---
name: llm
description: Use when text generation, image generation or editing, audio transcription, or mixed YAML orchestration tasks need to be handled through one unified CLI entry.
---

# llm skill

统一的 `llm` 命令行入口，用于：

- 文本生成、改写、总结、提取、翻译
- 图片生成、参考图编辑、多图生成
- 音频转录、字幕输出
- YAML 批量任务编排
- 按用户要求直接编辑文本文件

## 适用场景

当用户希望在终端里完成以下事情时，优先使用这个 skill：

- 生成一段文本、润色一份文案、总结多份资料
- 根据一张图来分析内容，或据此改写提示词
- 生成一张或多张图片
- 把音频转成文本或 SRT 字幕
- 用一个 YAML 文件批量执行多条任务
- 直接按要求修改某个文本文件

## chat

```bash
llm chat "写一段产品介绍"
llm chat @prompt.txt -o result.md
llm chat "总结重点" -i article.md -i notes.md
llm chat "整理为 JSON" -s @system.txt
llm chat "详细描述这张图的所有细节" -r photo.jpg
llm chat "把人物脸型改成偏瘦" --edit 商务女性生图.md
llm chat "按要求改写" --edit 商务女性生图.md -o 商务女性生图.v2.md
```

规则：

- `prompt` 支持字面量或 `@文件`
- `-s/--system` 支持字面量或 `@文件`
- `-i/--input` 可重复传入多个文本文件，作为补充上下文
- `-r/--reference` 可传入一张图片，用于视觉理解或图片分析
- `--edit` 用于编辑目标文本文件
- `--edit` 模式下，模型必须输出 `SEARCH/REPLACE` diff blocks，CLI 自动应用 diff
- `--edit` 不带 `-o` 时直接覆盖原文件；带 `-o` 时输出到新文件
- 非 edit 模式下，有 `-o` 时写入文件；无 `-o` 时输出到终端

## image

```bash
llm image "画一只猫"
llm image @prompt.txt -o cat.jpg
llm image "保留主体，改成极简插画风格" -r photo.jpg
llm image @prompt.txt -r ref.png -s @system.txt -o result.jpg
llm image "生成三张海报方案" -n 3 -o poster.jpg
```

规则：

- `prompt` 支持字面量或 `@文件`
- `-s/--system` 支持字面量或 `@文件`
- `-r/--reference` 为可选参考图
- `-n/--count` 用于控制生成数量，单命令多图会遵循 image 模式并发配置
- 多图模式会输出轻量进度：开始、每张完成、最终写入结果
- `-o poster.jpg -n 3` 时会输出为 `poster.jpg`、`poster_1.jpg`、`poster_2.jpg`
- 无 `-o` 时，默认输出到当前目录下的 `gemini-output/output_时间戳.jpg`

## audio

```bash
llm audio demo.mp3
llm audio demo.mp3 -o demo.srt
llm audio demo.mp3 -p @prompt.txt
llm audio demo.mp3 -p "请转成带说话人标注的 SRT" -s @system.txt
```

规则：

- 主位置参数必须是音频文件路径
- `-p/--prompt` 为可选附加要求，支持字面量或 `@文件`
- `-s/--system` 支持字面量或 `@文件`
- 无 `-o` 时，默认输出为音频同目录同名 `.srt`

## batch

```bash
llm batch tasks.yaml
```

执行时会输出：

- 上游地址
- 任务总数和并发数
- 每个任务的开始和完成状态（含使用的模型）

### YAML 示例

```yaml
mode: chat
system_prompt: "你是严谨的处理助手"
output_dir: outputs

tasks:
  - id: summary
    prompt: "总结下面内容"
    input: article.md
    output: summary.md

  - id: edit-prompt
    prompt: "把人物脸型改成偏瘦，不要改动其他描述"
    edit: 商务女性生图.md
    output: 商务女性生图.v2.md

  - id: hero-image
    mode: image
    prompt: "为产品主页生成三张极简横幅图"
    count: 3
    output: hero.jpg

  - id: transcript
    mode: audio
    audio_file: meeting.mp3
    prompt: "请输出标准 SRT 字幕"
```

### YAML 顶层字段

| 字段 | 必填 | 说明 | 可被 task 覆盖 |
|------|------|------|----------------|
| `mode` | ✓ | 默认任务类型：`chat` / `image` / `audio` | ✓ |
| `model` | | 全局模型名称，覆盖环境变量配置 | ✓ |
| `system_prompt` | | 全局 system prompt，支持 `@文件` | ✓ |
| `input` | | 全局输入文件（chat 模式），路径或路径数组 | ✓ |
| `reference` | | 全局参考图（chat/image 模式） | ✓ |
| `audio_file` | | 全局音频文件（audio 模式） | ✓ |
| `output_dir` | | 任务输出基目录，相对路径基于 YAML 所在目录 | - |
| `concurrency` | | 并发数 | - |
| `temperature` | | 温度参数（0.0-2.0） | ✓ |
| `max_output_tokens` | | 最大输出 token 数 | ✓ |
| `tasks` | ✓ | 任务数组，不能为空 | - |

### YAML task 字段

| 字段 | 必填 | 适用模式 | 说明 |
|------|------|----------|------|
| `id` | | 全部 | 任务标识，默认 `task-序号` |
| `mode` | | 全部 | 覆盖顶层 `mode` |
| `model` | | 全部 | 覆盖顶层 `model` |
| `prompt` | | 全部 | 支持字面量或 `@文件` |
| `system_prompt` | | 全部 | 覆盖顶层 `system_prompt`，支持 `@文件` |
| `input` | | chat | 覆盖顶层 `input`，路径或路径数组 |
| `reference` | | chat / image | 覆盖顶层 `reference` |
| `audio_file` | | audio | 覆盖顶层 `audio_file` |
| `edit` | | chat | 目标文本文件，进入 diff 编辑模式 |
| `count` | | image | 图片生成数量，遵循 image 模式并发配置 |
| `output` | | 全部 | 输出路径，未指定时使用默认规则 |
| `temperature` | | 全部 | 覆盖顶层 `temperature` |
| `max_output_tokens` | | 全部 | 覆盖顶层 `max_output_tokens` |

## 配置

脚本从 `~/.config/llm-api/.env` 读取配置，环境变量可覆盖：

```bash
API_KEY=your_api_key
BASE_URL=https://your-api-endpoint/v1
```

模型优先级：

| 模式 | 优先级 |
|------|--------|
| chat | `LLM_TEXT_MODEL` → `LLM_MODEL` → `OPENAI_CHAT_MODEL` → `OPENAI_MODEL` |
| image | `LLM_IMAGE_MODEL` → `LLM_MODEL` → `OPENAI_IMAGE_MODEL` |
| audio | `LLM_AUDIO_MODEL` → `LLM_MODEL` → `GEMINI_AUDIO_MODEL` |

并发优先级：

- 顶层 YAML `concurrency`
- `LLM_CONCURRENCY`
- 兼容旧变量（仅单一任务类型 batch 时生效）
- 默认 `4`

## 常见错误

| 问题 | 原因 | 正确方式 |
|------|------|----------|
| 把 YAML 文件直接传给 `chat` | `chat` 只处理单次任务 | 使用 `batch tasks.yaml` |
| audio 命令把文本写成第二个位置参数 | audio 只接受音频文件位置参数 | 用 `-p "你的要求"` |
| image/chat 想从文件读取 prompt 但直接写路径 | 未使用 `@` 前缀 | 用 `@prompt.txt` |
| 想编辑文本文件却传给 `-r` | `-r` 仅支持图片参考 | 用 `--edit file.md` |
| batch 中 audio 任务写成 `audio` 字段 | 字段名不对 | 使用 `audio_file` |

## --debug

`--debug` 可以放在任意位置：

```bash
llm --debug chat "test"
llm chat --debug "test"
llm chat "test" --debug
```

## 默认输出规则

| 模式 | 未指定输出时 |
|------|--------------|
| chat | 打印到终端 |
| image | `./gemini-output/output_时间戳.jpg` |
| audio | 输入音频同目录同名 `.srt` |
