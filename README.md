# shellus-llmcmd

**一个统一的 LLM 命令行工具。**

用一条 `llm` 命令，把日常 AI 工作流收敛到终端里：

- 写文案、总结、翻译、提取结构化数据
- 根据参考图生成或修改图片
- 把音频转成文本或 SRT 字幕
- 用 YAML 一次编排多条 chat / image / audio 任务
- 直接在终端里按要求编辑文本文件
- 用 JSONL 持久化 `chat` 会话，并在终端里连续对话

如果你希望把 LLM 能力稳定地接进 shell 脚本、自动化任务、个人工具链，而不是在多个网页和客户端之间切换，`shellus-llmcmd` 就是为这种场景准备的。

## 为什么用它

- **一个命令统一入口**：`chat`、`image`、`audio`、`batch`
- **终端友好**：天然适合 shell、cron、CI、脚本拼装
- **文件编辑能力**：`chat --edit` 直接按要求改文件
- **多图生成能力**：`image -n` 支持数量控制、并发控制和轻量进度输出
- **批处理能力**：YAML 一次组织多条任务
- **兼容 OpenAI 风格接口**：适合自建网关、代理层、兼容服务

## 安装

```bash
pip install shellus-llmcmd
```

安装后命令名是：

```bash
llm
```

## 使用场景

### 1. 直接生成文本

```bash
llm chat "写一段产品介绍"
llm chat @prompt.txt -o result.md
llm chat "总结重点" -i article.md -i notes.md
llm chat "继续上一轮结论" -s worklog
llm chat -I -s worklog
```

### 2. 直接修改文件

```bash
llm chat "把人物脸型改成偏瘦，不要改动其他描述" --edit prompt.md
llm chat "按要求改写" --edit prompt.md -o prompt.v2.md
```

### 3. 结合图片理解来写提示词

```bash
llm chat "详细描述这张图的所有细节" -r photo.jpg
llm chat "根据参考图修正人物外貌描述" --edit prompt.md -r ref.jpg
```

### 4. 一次生成多张图片

```bash
llm image "生成三张海报方案" -n 3 -o poster.jpg
```

输出结果示例：

- `poster.jpg`
- `poster_1.jpg`
- `poster_2.jpg`

### 5. 音频转录为字幕

```bash
llm audio demo.m4a -o demo.srt
llm audio demo.m4a -p "请转成带说话人标注的 SRT"
```

### 6. YAML 批量编排

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

## 命令速览

### `llm chat`
用于文本生成、分析、问答、改写、持久对话，以及 `--edit` 文件编辑。

新增会话参数：

- `-s/--session`：加载并持久化对话历史，值可为会话名或 `.jsonl` 路径
- `-I/--interactive`：进入交互式连续对话，默认持久化到当前目录下的 `.llm-chat.jsonl`

示例：

```bash
llm chat "总结上次方案并继续补充" -s product-review
llm chat -I
llm chat -I "你是什么模型？"
llm chat -I -s ./sessions/product-review.jsonl
```

说明：

- `-s product-review` 会落盘到当前目录下的 `product-review.jsonl`
- 单次模式和 `-I` 交互模式可共享同一个会话文件，随时切换继续
- `llm chat -I "首轮问题"` 会先发送这条首轮消息，再进入连续对话
- `-I` 模式下会先回放历史消息，响应流式打印到终端，按 `Ctrl+C` 结束
- `-I` 基于 `prompt_toolkit Application` 提供消息区、输入区和常驻状态栏
- 当前持久会话先聚焦连续文本对话，不与 `-i/-r/--edit/--system` 组合

### `llm image`
用于图片生成或参考图编辑，支持 `-n/--count` 多图生成。

### `llm audio`
用于音频转录，输出文本或 SRT。

### `llm batch`
用于 YAML 批量任务编排。

## 配置

`shellus-llmcmd` 默认从以下位置读取配置：

```bash
~/.config/llm-api/.env
```

最小配置示例：

```bash
API_KEY=your_api_key
BASE_URL=https://your-api-endpoint/v1
LLM_MODEL=your_default_model
```

如果你希望按能力拆分模型，也可以这样配置：

```bash
LLM_TEXT_MODEL=your_chat_model
LLM_IMAGE_MODEL=your_image_model
LLM_AUDIO_MODEL=your_audio_model
```

常用并发配置：

```bash
LLM_CONCURRENCY=4
OPENAI_CHAT_CONCURRENCY=4
OPENAI_IMAGE_CONCURRENCY=4
```

模型优先级：

- `chat`：`LLM_TEXT_MODEL` → `LLM_MODEL` → `OPENAI_CHAT_MODEL` → `OPENAI_MODEL`
- `image`：`LLM_IMAGE_MODEL` → `LLM_MODEL` → `OPENAI_IMAGE_MODEL`
- `audio`：`LLM_AUDIO_MODEL` → `LLM_MODEL` → `GEMINI_AUDIO_MODEL`

## 包信息

- PyPI 包名：`shellus-llmcmd`
- CLI 命令名：`llm`
- Python 要求：`>=3.10`

## 项目进度

- [x] 统一 `chat / image / audio / batch` 命令入口
- [x] `chat --edit` 文本编辑工作流
- [x] `image -n` 多图生成
- [x] `chat -s/-I` JSONL 持久会话与交互式流式对话
- [ ] 会话内建管理命令，如历史查看、清理、重命名
- [ ] 持久会话扩展到多模态连续编辑场景

## 详细文档

更完整的参数说明、YAML 字段说明和行为规则，请查看 [SKILL.md](./SKILL.md)。
