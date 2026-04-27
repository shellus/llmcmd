# Configuration

`CONFIGURATION.md` 是 `shellus-llmcmd` 的配置唯一事实来源，集中说明配置文件、优先级、模型解析、协议选择、运行时覆盖和常见排查。

## 文档定位

项目文档按职责分工：

- `README.md`：项目介绍、安装方式、命令用法、常见场景和基础注意事项
- `SKILL.md`：面向 Agent 和终端自动化的完整调用手册
- `CONFIGURATION.md`：配置字段、解析规则、协议列表、配置示例和排查流程
- `DEVELOPING.md`：面向维护者的代码结构、设计边界和文档维护规则

配置字段含义、`protocol` 可选值、模型解析优先级和 provider 行为以本文档为准。

## 配置文件

`shellus-llmcmd` 默认读取两个文件：

```bash
~/.llm/.env
~/.llm/config.yaml
```

- `~/.llm/.env`：保存密钥、网关地址、临时可覆盖变量等环境变量
- `~/.llm/config.yaml`：声明 provider、mode、model、protocol、alias、defaults、reference_transport 等结构化配置

密钥、域名、账号、私有地址等环境相关内容应放入 `.env` 或运行时环境变量，不应写入项目仓库中的示例配置。

## 核心概念

| 概念 | 含义 | 示例 |
|------|------|------|
| `mode` | CLI 任务类型，决定命令入口和输出处理流程 | `chat`、`image`、`tts`、`video` |
| `provider` | 上游服务或兼容网关配置，包含 `base_url` 与 `api_key` | `openai`、`gemini`、`reverse-video` |
| `model` | 发给上游的模型名，也可配置 alias | `gpt-4.1`、`gpt-image-1` |
| `protocol` | CLI 与上游交互时使用的请求协议 | `openai-chat-completions`、`openai-responses` |
| `alias` | 给 CLI 使用的模型短名称 | `chat-default`、`sora-fast` |
| `defaults` | 模型默认请求参数 | `size: 720p`、`aspect_ratio: "16:9"` |
| `reference_transport` | 本地参考文件预上传为 URL 的传输配置 | `aliyun-s3` |

关键边界：

- `mode` 不等于模型能力。`llm image` 使用图片任务流程，但实际能否返回图片取决于所选模型和后端能力。
- `protocol` 不等于模型能力。它只描述请求方式和结果提取方式。
- `--model` 不只覆盖模型名；若命中某个 provider 下的模型名或 alias，也会切换到该 provider。

## 配置加载流程

```text
启动 llm
  |
  v
[进程环境变量]
  |
  | 1. 先读取命令启动时已有的环境变量
  |    例如:
  |    CHAT_MODEL / IMAGE_MODEL / TTS_MODEL / VIDEO_MODEL / MODEL
  |    BASE_URL / API_KEY
  |
  v
[读取 ~/.llm/.env]
  |
  | 2. 仅把进程环境中不存在的变量补入环境
  |    即:
  |    运行时环境变量 > ~/.llm/.env
  |
  v
[读取 ~/.llm/config.yaml]
  |
  | 3. 用当前环境展开 ${ENV_NAME}
  |    即:
  |    运行时环境变量 > ~/.llm/.env > config.yaml 中的 ${...} 引用值
  |
  v
[按 mode 解析 provider / model / protocol / reference_transport]
  |
  v
[创建客户端并执行命令]
```

## 优先级

### 模型 `model`

```text
--model
  > mode 专属环境变量
  > MODEL
  > modes.<mode>.model
  > default_model
```

按 mode 展开后：

- `chat`：`--model` > `CHAT_MODEL` > `MODEL` > `modes.chat.model` > `default_model`
- `image`：`--model` > `IMAGE_MODEL` > `MODEL` > `modes.image.model` > `default_model`
- `tts`：`--model` > `TTS_MODEL` > `MODEL` > `modes.tts.model` > `default_model`
- `video`：`--model` > `VIDEO_MODEL` > `MODEL` > `modes.video.model` > `default_model`

### provider

```text
若 --model 命中某个 provider 下的模型名或 alias
  -> 切换到该 provider
否则
  -> modes.<mode>.provider
     > default_provider
```

`--model` 可用于选择已定义模型、选择 alias，或临时指定未在配置中声明的新模型名。

### `base_url` 与 `api_key`

```text
BASE_URL > providers.<selected>.base_url
API_KEY  > providers.<selected>.api_key
```

`BASE_URL` 与 `API_KEY` 对当前命令整体生效，不区分 `chat / image / tts / video`。

### `.env` 与进程环境

```text
进程环境变量 > ~/.llm/.env
```

`~/.llm/.env` 只补充缺失项，不覆盖命令启动时已经存在的环境变量。

## `protocol` 可选值

| protocol | 适用 mode | 请求方式 | 主要用途 |
|----------|-----------|----------|----------|
| `openai-chat-completions` | `chat`、`image` | `POST /v1/chat/completions` | 默认 OpenAI 兼容文本、多模态和图片链路 |
| `openai-responses` | `image` | `POST /v1/responses` + SSE | 仅支持 Responses API 的图片模型 |
| `grok2api-image` | `image` | `POST /v1/chat/completions` | Grok2API 风格图片 URL 提取变体 |
| `gemini-generate-content` | `tts` | `POST /v1beta/models/{model}:generateContent` | Gemini 原生 TTS |
| `openai-videos` | `video` | `POST /v1/videos` | OpenAI 风格视频任务 |
| `unified-video` | `video` | 兼容网关统一视频接口 | NewAPI/兼容网关视频任务 |

补充说明：

- 解析配置时会校验最终生效的 `protocol`；未在表中的值会直接报错，不会静默回退。
- 解析配置时也会校验 `protocol` 是否适用于当前 mode；例如 `gemini-generate-content` 当前只适用于 `tts`，不能用于 `image`。
- `openai-chat-completions` 是 `chat / image` 默认协议；图片参考按 `image_url` data URL 发送。
- `openai-responses` 固定按 SSE 收集 Responses API 事件，并从图片结果事件中提取输出。
- `grok2api-image` 仍走 chat completions，但结果优先从 `message.content` 中提取图片 URL。
- `gemini-generate-content` 当前用于 `tts`，由 Gemini 原生响应中的 PCM 音频封装为 wav。
- `openai-videos` 与 `unified-video` 都是异步视频任务协议，创建任务后轮询并下载结果。

## 配置字段说明

| 字段 | 说明 |
|------|------|
| `default_provider` | 各 mode 未声明 provider 时使用的默认 provider |
| `default_model` | 各 mode 未声明 model 时使用的默认模型 |
| `concurrency` | 全局并发默认值 |
| `modes.<mode>.provider` | 指定 mode 默认 provider |
| `modes.<mode>.model` | 指定 mode 默认模型 |
| `modes.<mode>.protocol` | 指定 mode 默认协议 |
| `modes.<mode>.reference_transport` | 指定 mode 默认参考文件传输方式 |
| `providers.<name>.base_url` | 上游接口地址 |
| `providers.<name>.api_key` | 上游鉴权密钥，通常引用 `${ENV_NAME}` |
| `providers.<name>.models.<model_name>.type` | 模型所属 mode |
| `providers.<name>.models.<model_name>.alias` | CLI 可使用的模型别名 |
| `providers.<name>.models.<model_name>.protocol` | 模型强制使用的协议 |
| `providers.<name>.models.<model_name>.reference_transport` | 模型对应的参考文件传输方式 |
| `providers.<name>.models.<model_name>.defaults` | 写入请求的模型默认参数 |
| `reference_transports.<name>` | 可复用的参考文件上传目标 |

## 快速开始配置

首次使用时，准备依赖与配置目录：

```bash
pip install -U shellus-llmcmd openai pyyaml
mkdir -p ~/.llm
```

创建 `~/.llm/.env`：

```bash
cat > ~/.llm/.env <<'EOF'
OPENAI_API_KEY=your_openai_api_key
REVERSE_VIDEO_KEY=your_reverse_video_key
USER_AGENT=curl/8.5.0
EOF
```

创建 `~/.llm/config.yaml`：

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
  tts:
    provider: gemini
    model: gemini-3.1-flash-tts-preview
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
      gpt-image-2:
        type: image
        protocol: openai-responses

  gemini:
    base_url: https://generativelanguage.googleapis.com
    api_key: ${OPENAI_API_KEY}
    models:
      gemini-3.1-flash-tts-preview:
        type: tts
        protocol: gemini-generate-content

  reverse-video:
    base_url: https://your-newapi.example.com/v1
    api_key: ${REVERSE_VIDEO_KEY}
    models:
      sora_t2v_turbo:
        type: video
        alias: sora-fast
        protocol: unified-video
```

验证配置：

```bash
llm chat "你好，输出一句测试文本"
```

## 完整配置示例

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
  tts:
    provider: gemini
    model: gemini-3.1-flash-tts-preview
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
      gpt-image-2:
        type: image
        protocol: openai-responses

  gemini:
    base_url: https://generativelanguage.googleapis.com
    api_key: ${OPENAI_API_KEY}
    models:
      gemini-3.1-flash-tts-preview:
        type: tts
        protocol: gemini-generate-content

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

## 运行时环境变量覆盖

这些变量可直接写在命令前，仅对当前命令生效，不会写回 `~/.llm/.env` 或 `~/.llm/config.yaml`。

常用变量：

- `CHAT_MODEL`：覆盖 `chat` 默认模型
- `IMAGE_MODEL`：覆盖 `image` 默认模型
- `TTS_MODEL`：覆盖 `tts` 默认模型
- `VIDEO_MODEL`：覆盖 `video` 默认模型
- `MODEL`：通用模型覆盖；未设置 mode 专属变量时生效
- `BASE_URL`：临时覆盖当前 provider 的 `base_url`
- `API_KEY`：临时覆盖当前 provider 的 `api_key`
- `USER_AGENT`：覆盖请求头中的 User-Agent

示例：

```bash
CHAT_MODEL=gpt-5.4 llm chat "用更强模型重写这段文案"
IMAGE_MODEL=gpt-image-1 llm image "生成一张横版海报" -o banner.jpg
TTS_MODEL=gemini-3.1-flash-tts-preview llm tts "请朗读一句欢迎词" -o welcome.wav
BASE_URL=https://gateway.example.com/v1 API_KEY=sk-test CHAT_MODEL=gpt-5.4 llm chat "输出一句自检文本"
BASE_URL=https://gateway.example.com/v1 API_KEY=sk-test IMAGE_MODEL=gpt-image-1 llm image "生成产品主图" -o hero.jpg
```

## `--model` 解析规则

传入 `--model` 时，CLI 会先在所有 provider 下查找与该值匹配的模型名或 `alias`。

```text
传入 --model foo
  |
  +-- 若 foo 唯一命中某个 provider 的 model name 或 alias
  |     -> 使用该 provider
  |     -> 使用命中的真实模型名
  |
  +-- 若 foo 在多个 provider 中重复命中
  |     -> 直接报错
  |
  +-- 若 foo 没有命中任何已定义模型
        -> 仍使用 foo 作为最终模型名
        -> provider 不变，继续使用 mode 默认 provider
```

典型用途：

- 选择已在 `config.yaml` 中定义过的模型或 alias
- 临时指定一个未在 `config.yaml` 中显式声明的新模型名
- 通过 alias 在不同 provider 或真实模型名之间切换

## 图片模型与 `llm image`

`llm image` 的职责是构造图片任务输入、发送图片生成请求、提取图片结果并落盘。它不保证任意模型都会返回图片。

常见组合：

| 场景 | 推荐处理 |
|------|----------|
| OpenAI 风格图片模型 | 使用 `image` mode，通常走 `openai-chat-completions` 或后端指定协议 |
| 仅支持 Responses API 的图片模型 | 在模型配置中声明 `protocol: openai-responses` |
| 兼容网关中的 Gemini 图片模型 | 使用 provider 中实际支持图片输出的模型名 |
| 多模态理解模型 | 使用 `chat -r` 做理解、描述、转写或分析；不应期待返回图片 |

排查原则：

- 命令使用 `llm image` 但响应只有文字时，优先检查模型是否具备图片生成能力。
- `--size` 与 `--aspect` 只表示图片请求参数；实际生效情况取决于模型和后端适配。
- `--debug` 只能显示 CLI 发送的请求结构，不能证明上游一定按该参数生成指定分辨率。

## 参考文件传输 `reference_transport`

默认情况下，本地图片参考会以内联 data URL 发送给 OpenAI 兼容接口。部分视频或网关链路要求参考文件是可访问 URL，此时可配置 `reference_transport`。

`reference_transport` 的典型用途：

- 把本地参考图上传到 S3 兼容存储
- 把上传后的公开 URL 写入上游请求
- 避免上游无法读取本地文件或 data URL

当前实现中，`reference_transport` 可在 mode 或单个模型上声明。单个模型配置优先于 mode 配置。

## 常见排查

若命令启动或执行结果异常，按以下顺序检查：

1. `~/.llm/config.yaml` 是否存在且为合法 YAML。
2. YAML 中引用的 `${ENV_NAME}` 是否能在当前环境或 `~/.llm/.env` 中找到。
3. 对应 provider 是否同时声明了 `base_url` 和 `api_key`。
4. `modes.<mode>.model` 是否能在对应 provider 的 `models` 中找到。
5. `--model` 或运行时模型变量是否拼写错误。
6. `BASE_URL` / `API_KEY` 是否把原有 provider 连接信息覆盖成错误值。
7. `protocol` 是否属于本文档列出的可选值，并适用于当前 mode。
8. 当前模型和后端能力是否支持目标任务，例如图片任务是否选择了真正支持图片输出的模型。
9. 音频理解与视频理解是否使用 `llm chat -r`，而不是已删除的旧 `audio` 子命令。
10. 本机是否已安装 `openai` 与 `pyyaml`。

## 相关文档

- 项目主文档：[`README.md`](./README.md)
- Agent 使用手册：[`SKILL.md`](./SKILL.md)
- 开发参考：[`DEVELOPING.md`](./DEVELOPING.md)
- Responses 图片模型专题：[`docs/模型能力和请求方式/gpt-image-2.md`](./docs/模型能力和请求方式/gpt-image-2.md)
