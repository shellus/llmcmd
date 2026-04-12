---
name: llmcmd
description: Use when handling terminal-first LLM workflows for text generation, image generation, audio transcription, video generation, YAML batch tasks, persistent chat sessions, or file-based prompt and reference inputs.
---

# llmcmd

`shellus-llmcmd` 是一个统一的 LLM 命令行工具，入口命令是 `llm`。

本手册面向直接调用本项目的 Agent 或终端用户，覆盖当前可用能力、常见参数、配置方法与高频示例。

## 适用场景

在以下场景使用本技能：

- 需要把文本、图片、音频、视频能力统一接入 shell、脚本、自动化流程或 CI
- 需要读取本地文本、图片、文档、音频作为 prompt 或参考输入
- 需要用 `chat --edit` 按要求直接修改文本文件
- 需要在终端里持久化会话并继续同一轮对话
- 需要通过 YAML 一次编排多条 `chat / image / audio / video` 任务

## 安装

```bash
pip install shellus-llmcmd
```

安装后命令名是：

```bash
llm
```

## 能力概览

| 模式 | 用途 | 常用输入 | 常用输出 |
|------|------|----------|----------|
| `llm chat` | 文本生成、分析、问答、改写、编辑文件、持久对话 | prompt、`@文件`、`-r` 附件、会话文件 | stdout、文本文件、会话文件 |
| `llm agent` | 启动 `pi` coding agent，并复用当前 `chat` 配置 | prompt、`--thinking`、`--session`、`--tools` | `pi` 交互会话 |
| `llm image` | 图片生成、参考图编辑 | prompt、`@文件`、`-r` 附件 | 图片文件 |
| `llm audio` | 音频转写、总结、字幕 | prompt、音频附件 | stdout、文本文件、字幕文件 |
| `llm video` | 异步视频生成、恢复等待、自动下载 | prompt、首帧参考图、任务 ID | 视频文件 |
| `llm batch` | YAML 批量任务编排 | `tasks.yaml` | 输出目录内多个结果 |

## 常用输入规则

### 1. 直接写 prompt

```bash
llm chat "写一段产品介绍"
llm image "生成横版海报"
llm video "生成一段海边航拍视频"
```

### 2. 使用 `@文件`

`@文件` 会把文本文件内容直接读入 prompt，适合长提示词或模板化输入。

```bash
llm chat @prompt.txt -o result.md
llm image @prompt.md -o result.jpg
```

### 3. 使用 `-r/--reference`

`-r/--reference` 用于提供参考输入。可传多次。

```bash
llm chat "总结这个附件的重点" -r report.pdf
llm chat "对比两张参考图后总结共同特征" -r photo-a.jpg -r photo-b.jpg
llm image "融合两张参考图的风格生成图片" -r person.jpg -r style.jpg -o result.jpg
llm audio "总结录音内容" -r meeting.m4a
llm video "生成产品展示短片" -r first-frame.jpg --seconds 8 -o demo.mp4
```

补充规则：

- `chat` 中，图片参考会作为图片输入，文本类附件优先内联为文本
- `image / audio` 中，参考输入按文件附件处理
- `video` 当前仅使用第一张参考图作为首帧参考

## `llm chat`

用于文本生成、分析、问答、改写、结构化提取、文件编辑与持久化对话。

### 基本示例

```bash
llm chat "写一段产品介绍"
llm chat @prompt.txt -o result.md
llm chat "总结重点" -r article.md -r notes.pdf
llm chat "根据参考图修正人物外貌描述" --edit prompt.md -r ref.jpg
```

### 文件编辑

`chat --edit` 会按要求修改目标文本文件。

```bash
llm chat "把人物脸型改成偏瘦，不要改动其他描述" --edit prompt.md
llm chat "按要求改写" --edit prompt.md -o prompt.v2.md
```

适用场景：

- 改写提示词
- 修正文案
- 在保留原结构的前提下做局部调整

### 持久化会话

新增会话参数：

- `-s/--session`：加载并持久化对话历史，值可为会话名或 `.jsonl` 路径
- `-I/--interactive`：进入交互式连续对话；默认仅保存在内存中，配合 `-s` 才会加载并持久化

示例：

```bash
llm chat "继续上一轮结论" -s worklog
llm chat -I
llm chat -I "你是什么模型？"
llm chat -I -s ./sessions/product-review.jsonl
```

说明：

- `--provider` 可临时覆盖当前 chat 模式使用的 provider
- `--model` 与 `--provider` 同时使用时，会优先在该 provider 下解析模型别名；未命中时直接按原始模型名发送
- `-s product-review` 会写到当前目录下的 `product-review.jsonl`
- 单次模式和 `-I -s ...` 交互模式可共享同一个会话文件
- `llm chat -I "首轮问题"` 会先发送首轮消息，再进入连续对话
- `-I` 模式下只有配合 `-s` 才会回放历史并持续写回；不带 `-s` 时为纯内存会话
- 当前持久会话聚焦连续文本对话，不与 `-r/--edit` 组合
- `chat -s ... --system ...` 与 `chat -I -s ... --system ...` 会把 system prompt 写入会话历史；再次带 `--system` 启动同一会话时，只覆盖会话开头连续的 system 消息

交互式内置命令：

- `/clear`：清空当前会话
- `/model <name>`：切换当前模型，并写回 `~/.llm/.env` 中的 `CHAT_MODEL`
- `/save <name-or-path>`：将当前会话保存到指定文件

交互细节：

- 基于 `Textual` 全屏 TUI
- `Enter` 发送
- `Shift+Enter` 或 `Ctrl+J` 换行
- 如需终端原生鼠标拖选复制历史消息，需按住终端模拟器修饰键；当前环境实测为按住 `Shift`

### 输出行为

- 非交互 `chat` 会实时把流式文本写到 stdout
- 若 `chat` 使用图片模型并返回图片，会自动落盘并显示图片路径

## `llm agent`

用于启动外部 `pi` coding agent，并复用当前 `llmcmd` 的 `chat` 模型、`BASE_URL` 与 `API_KEY` 配置。

### 基本示例

```bash
llm agent
llm agent "审查当前仓库里最危险的改动"
llm agent --model qwen3-coder --thinking high
llm agent --session ./pi-session.jsonl --tools read,grep,find,ls
```

### 说明

- `--provider` 可临时覆盖当前 agent 复用的 chat provider
- `--model` 与 `--provider` 同时使用时，会优先在该 provider 下解析模型别名；未命中时直接按原始模型名发送
- 这是独立入口，不替换现有 `chat -I`
- 运行时会在 `~/.llm/pi-agent/` 下生成 `pi` 所需的 `models.json`
- `models.json` 只写 `base_url` 与 API key 的环境变量名，真实 key 通过子进程环境变量注入
- `agent` 当前使用 `chat` 模式配置作为上游来源
- `--thinking` 会透传给 `pi`；当值不是 `off` 时，默认把该模型标记为 reasoning
- `--pi-bin` 可指定 `pi` 可执行文件路径
- `--session`、`--session-dir`、`--no-session`、`--tools`、`--no-tools` 会原样透传给 `pi`

## `llm image`

用于图片生成或参考图编辑，支持多图生成。

### 基本示例

```bash
llm image "生成三张海报方案" -n 3 -o poster.jpg
llm image "融合两张参考图的风格生成情侣自拍" -r person.jpg -r style.jpg -o couple.jpg
llm image @prompt.md -r ref.jpg -o output.jpg
llm image @prompts/couple-photo.md -r refs/person-a.jpg -r refs/person-b.jpg -o outputs/couple-photo/result.jpg -n 4
llm image "生成横版海报" --size 2K --aspect 16:9 -o banner.jpg
```

输出结果示例：

- `poster.jpg`
- `poster_1.jpg`
- `poster_2.jpg`

### 常用参数

- `-n/--count`：生成数量
- `--provider`：临时覆盖当前 image 模式使用的 provider
- `--model`：临时覆盖当前 image 模式使用的模型
- `--size`：支持 `512 / 1K / 2K / 4K`
- `--aspect`：支持 `1:1 / 16:9 / 9:16 / 4:3 / 3:4 / 3:2 / 2:3 / 4:5 / 5:4 / 21:9`

说明：

- `--size` 和 `--aspect` 的实际生效情况取决于图片后端
- `image` 当前统一通过流式请求收集结果
- `-r/--reference` 默认按 `type=file` 发送；当配置了 `reference_transport` 且图片参考已预上传为 URL 时，会优先改用 `image_url`
- `--provider` 与 `--model` 同时使用时，会优先在该 provider 下解析模型别名；未命中时直接按原始模型名发送

## `llm audio`

用于把音频送入模型处理，可做转写、总结、字幕生成。

### 基本示例

```bash
llm audio -r demo.m4a
llm audio "总结录音内容" -r demo.m4a
llm audio "请输出标准 SRT 字幕" -r demo.m4a -o demo.srt
```

说明：

- `--provider` 可临时覆盖当前 audio 模式使用的 provider
- `--model` 与 `--provider` 同时使用时，会优先在该 provider 下解析模型别名；未命中时直接按原始模型名发送
- 位置参数是 prompt
- `-r/--reference` 上传音频附件
- 默认实时输出到 stdout，仅在传 `-o` 时写文件
- 若要 SRT，请直接在 prompt 中明确要求

## `llm video`

用于异步视频生成。默认会创建任务、等待完成并自动下载，也支持按任务 ID 恢复等待并下载。

### 基本示例

```bash
llm video "生成一段海边航拍视频"
llm video "生成产品展示短片" -r first-frame.jpg --seconds 8 --size 720x1280 -o demo.mp4
llm video --resume vid_123 -o demo.mp4
```

说明：

- `--provider` 可临时覆盖当前 video 模式使用的 provider
- `--model` 与 `--provider` 同时使用时，会优先在该 provider 下解析模型别名；未命中时直接按原始模型名发送
- `video` 默认先创建异步任务，再持续等待完成并自动下载
- 创建成功后会先打印任务 ID，便于中断后用 `--resume` 恢复
- `-r/--reference` 当前仅取第一张图作为 `input_reference`
- 下载固定走 `GET /v1/videos/{id}/content`

常用参数：

- `--seconds`：支持 `4 / 8 / 12 / 16 / 20`
- `--size`：当前支持 `720x1280 / 1280x720 / 1024x1024`

## `llm batch`

用于 YAML 批量任务编排。

### 基本示例

```bash
llm batch tasks.yaml
```

说明：

- `--provider` 可统一覆盖 batch 内各任务默认使用的 provider

示例：

```yaml
mode: chat
system_prompt: "你是严谨的处理助手"
output_dir: outputs

tasks:
  - prompt: "总结下面内容"
    input: article.md
    output: summary.md

  - prompt: "把人物脸型改成偏瘦，不要改动其他描述"
    edit: 商务女性生图.md
    output: 商务女性生图.v2.md

  - mode: image
    prompt: "为产品主页生成三张极简横幅图"
    count: 3
    size: 2K
    aspect: "16:9"
    output: hero.jpg

  - mode: audio
    audio_file: meeting.mp3
    prompt: "请输出标准 SRT 字幕"

  - mode: video
    prompt: "生成一段产品宣传短片"
    reference:
      - cover.jpg
    seconds: "8"
    size: 720x1280
    output: promo.mp4
```

说明：

- 顶层 `mode` 可为任务提供默认模式
- 单个任务可通过 `mode` 覆盖默认值
- 如果定义了 `output`，始终以 `output` 为准
- 图片和视频任务未定义 `output` 时，会按任务序号自动命名为 `image-1.jpg`、`video-2.mp4`
- `aspect` 建议写成带引号的字符串，例如 `"16:9"`，避免 YAML 误解析

## 配置

默认从以下位置读取配置：

```bash
~/.llm/.env
~/.llm/config.yaml
```

加载顺序：

1. 先读取 `~/.llm/.env`，将其中变量写入进程环境；若命令启动时已经存在同名环境变量，则保留运行时环境变量
2. 再读取 `~/.llm/config.yaml`
3. 解析 YAML 中的 `${ENV_NAME}` 占位符
4. 命令执行阶段统一从内存中的配置实例读取 provider、model、base_url、api_key、protocol 等字段

### 快速开始

首次使用时，先准备依赖与配置目录：

```bash
pip install -U shellus-llmcmd openai pyyaml
mkdir -p ~/.llm
```

然后创建 `~/.llm/.env`：

```bash
cat > ~/.llm/.env <<'EOF'
OPENAI_API_KEY=your_openai_api_key
REVERSE_VIDEO_KEY=your_reverse_video_key
EOF
```

再创建 `~/.llm/config.yaml`：

```yaml
default_provider: openai
concurrency: 4

modes:
  chat:
    provider: openai
    model: gpt-4.1
  image:
    provider: openai
    model: gpt-image-1
  audio:
    provider: openai
    model: gpt-4o-transcribe
  video:
    provider: reverse-video
    model: sora_t2v_turbo

providers:
  openai:
    base_url: https://api.openai.com/v1
    api_key: ${OPENAI_API_KEY}
    models:
      gpt-4.1:
        type: chat
      gpt-image-1:
        type: image
      gpt-4o-transcribe:
        type: audio

  reverse-video:
    base_url: https://your-newapi.example.com/v1
    api_key: ${REVERSE_VIDEO_KEY}
    models:
      sora_t2v_turbo:
        type: video
        protocol: unified-video
```

配置完成后，可先验证：

```bash
llm chat "你好，输出一句测试文本"
```

若启动时报错，优先检查：

- `~/.llm/config.yaml` 是否存在且为合法 YAML
- `.env` 中引用的环境变量是否与 `config.yaml` 中的 `${...}` 一致
- 对应 provider 是否同时声明了 `base_url` 和 `api_key`
- `modes.<mode>.model` 是否能在对应 provider 的 `models` 中找到
- 本机是否已安装 `openai` 与 `pyyaml`

### `.env` 示例

```bash
OPENAI_API_KEY=your_openai_api_key
REVERSE_VIDEO_KEY=your_reverse_video_key
USER_AGENT=curl/8.5.0
```

### `config.yaml` 示例

```yaml
default_provider: openai
concurrency: 4

modes:
  chat:
    provider: openai
    model: gpt-4.1
  image:
    provider: openai
    model: gpt-image-1
  audio:
    provider: openai
    model: gpt-4o-transcribe
  video:
    provider: reverse-video
    model: sora_t2v_turbo

providers:
  openai:
    base_url: https://api.openai.com/v1
    api_key: ${OPENAI_API_KEY}
    models:
      gpt-4.1:
        type: chat
        alias: chat-default
      gpt-image-1:
        type: image
      gpt-4o-transcribe:
        type: audio

  reverse-video:
    base_url: https://your-newapi.example.com/v1
    api_key: ${REVERSE_VIDEO_KEY}
    models:
      sora_t2v_turbo:
        type: video
        alias: sora-fast
        protocol: unified-video
        reference_transport: aliyun-s3
        defaults:
          aspect_ratio: "16:9"
          size: 720p
      sora_t2v_pro:
        type: video
        alias: sora-pro
        protocol: unified-video
        reference_transport: aliyun-s3

reference_transports:
  aliyun-s3:
    endpoint: ${ALIYUN_S3_ENDPOINT}
    bucket: ${ALIYUN_S3_BUCKET}
    region: ${ALIYUN_S3_REGION}
    access_key_id: ${ALIYUN_S3_ACCESS_KEY_ID}
    secret_access_key: ${ALIYUN_S3_SECRET_ACCESS_KEY}
    public_base_url: ${ALIYUN_S3_PUBLIC_BASE_URL}
    key_prefix: llmcmd
```

配置说明：

- `modes.<mode>`：声明每个 CLI mode 默认使用哪个 provider、哪个真实模型
- `providers.<name>`：声明上游的 `base_url`、`api_key`
- `providers.<name>.models.<model_name>`：声明模型的 `type / alias / protocol / reference_transport / defaults`
- `protocol` 当前支持 `openai-chat-completions`、`grok2api-image`、`openai-videos` 与 `unified-video`
- `reference_transport` 可把本地参考文件先上传到命名的 S3 兼容存储，再将 URL 提供给上游
- `reference_transports.<name>`：声明可复用的 S3 兼容上传目标
- `alias` 可将 CLI 中使用的短名称映射到真实模型名
- 可通过运行时环境变量覆盖 `.env`，例如 `OPENAI_API_KEY=xxx llm chat "hello"`
- `--model` 会覆盖当前 mode 的默认模型；若该值命中某个 provider 下模型的 `alias`，会自动路由到该真实模型

临时试用额外模型或 URL：

有些场景只想在当前命令里试一个额外模型、临时网关或测试密钥，不希望写入 `~/.llm/.env` 或 `~/.llm/config.yaml`。可以直接在命令前设置运行时环境变量，这些值只对当前这条命令生效，并且优先级高于 `.env`。

```bash
CHAT_MODEL=gpt-5.4 llm chat "用更强模型重写这段文案"
IMAGE_MODEL=gemini-2.5-flash-image-preview llm image "生成一张横版海报" -o banner.jpg
BASE_URL=https://gateway.example.com/v1 API_KEY=sk-test CHAT_MODEL=gpt-5.4 llm chat "输出一句自检文本"
BASE_URL=https://gateway.example.com/v1 API_KEY=sk-test IMAGE_MODEL=seedream-4.0 llm image "生成产品主图" -o hero.jpg
```

常用运行时变量：

- `CHAT_MODEL`：覆盖 `chat` 默认模型
- `IMAGE_MODEL`：覆盖 `image` 默认模型
- `AUDIO_MODEL`：覆盖 `audio` 默认模型
- `VIDEO_MODEL`：覆盖 `video` 默认模型
- `MODEL`：作为通用模型覆盖；未设置 mode 专属变量时生效
- `BASE_URL`：临时覆盖当前 provider 的 `base_url`
- `API_KEY`：临时覆盖当前 provider 的 `api_key`

说明：

- 这类覆盖不会修改任何配置文件，命令结束后即失效
- 如果同时设置了 mode 专属变量和 `MODEL`，优先使用 mode 专属变量
- `BASE_URL` 与 `API_KEY` 是对当前命令整体生效，不区分 `chat / image / audio / video`

## 常见工作流

### 1. 总结文档

```bash
llm chat "总结下面内容" -r article.md -o summary.md
```

### 2. 基于参考图修正文案

```bash
llm chat "根据参考图修正人物外貌描述" --edit prompt.md -r ref.jpg
```

### 3. 生成多张图片方案

```bash
llm image "生成三张海报方案" -n 3 -o poster.jpg
```

### 4. 转写录音并输出字幕

```bash
llm audio "请输出标准 SRT 字幕" -r demo.m4a -o demo.srt
```

### 5. 创建并恢复视频任务

```bash
llm video "生成产品展示短片" -r first-frame.jpg --seconds 8 -o demo.mp4
llm video --resume vid_123 -o demo.mp4
```

### 6. 继续同一轮对话

```bash
llm chat "继续上次方案" -s worklog
llm chat -I -s worklog
```

## 常见错误

- 把长文本直接硬编码到命令里，而不是用 `@文件`
- 需要多轮对话却没用 `-s`，导致上下文无法复用
- 在 YAML 里把 `aspect` 写成未加引号的 `16:9`，被 YAML 误解析
- 期待 `audio` 自动输出 SRT，但 prompt 没明确要求字幕格式
- 忘记 `video` 是异步任务，未记录任务 ID
- 把域名、密钥、账号写进版本控制文件，而不是放进 `.env`

## 包信息

- PyPI 包名：`shellus-llmcmd`
- CLI 命令名：`llm`
- Python 要求：`>=3.10`

## 相关文档

- 开发参考：[`DEVELOPING.md`](./DEVELOPING.md)
