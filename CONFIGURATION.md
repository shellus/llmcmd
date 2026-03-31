# Configuration

`shellus-llmcmd` 默认通过下面两个文件建立运行时配置：

```bash
~/.llm/.env
~/.llm/config.yaml
```

本文档说明当前实现中的配置来源、优先级、运行时覆盖方式，以及 `--model` 与 provider 的解析关系。

## 配置加载流程

```text
启动 llm
  |
  v
[进程环境变量]
  |
  | 1. 先读取命令启动时已有的环境变量
  |    例如:
  |    CHAT_MODEL / IMAGE_MODEL / AUDIO_MODEL / VIDEO_MODEL / MODEL
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
[创建 OpenAI 兼容客户端并执行命令]
```

## 最终优先级

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
- `audio`：`--model` > `AUDIO_MODEL` > `MODEL` > `modes.audio.model` > `default_model`
- `video`：`--model` > `VIDEO_MODEL` > `MODEL` > `modes.video.model` > `default_model`

### provider

```text
若 --model 命中某个 provider 下的模型名或 alias
  -> 切换到该 provider
否则
  -> modes.<mode>.provider
     > default_provider
```

这意味着 `--model` 不只是覆盖模型名，也可能改变最终选中的 provider。

### `base_url` 与 `api_key`

```text
BASE_URL > providers.<selected>.base_url
API_KEY  > providers.<selected>.api_key
```

`BASE_URL` 与 `API_KEY` 是对当前命令整体生效的覆盖，不区分 `chat / image / audio / video`。

### `.env` 与进程环境

```text
进程环境变量 > ~/.llm/.env
```

`~/.llm/.env` 只补充缺失项，不会覆盖命令启动时已经存在的环境变量。

## 快速开始

首次使用时，先准备依赖与配置目录：

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

配置完成后，可先验证：

```bash
llm chat "你好，输出一句测试文本"
```

## 配置项说明

- `default_provider`：各 mode 未单独声明 provider 时的默认 provider
- `default_model`：各 mode 未单独声明 model 时的默认 model
- `concurrency`：全局并发默认值
- `modes.<mode>.provider`：该 mode 的默认 provider
- `modes.<mode>.model`：该 mode 的默认模型
- `modes.<mode>.protocol`：该 mode 的默认协议
- `modes.<mode>.reference_transport`：该 mode 默认使用的参考文件传输方式
- `providers.<name>.base_url`：上游 OpenAI 兼容接口地址
- `providers.<name>.api_key`：上游鉴权密钥
- `providers.<name>.models.<model_name>`：模型定义
- `providers.<name>.models.<model_name>.type`：模型所属 mode
- `providers.<name>.models.<model_name>.alias`：给 CLI 使用的别名
- `providers.<name>.models.<model_name>.protocol`：该模型强制使用的协议
- `providers.<name>.models.<model_name>.reference_transport`：该模型对应的参考文件传输方式
- `providers.<name>.models.<model_name>.defaults`：写入请求的模型默认参数
- `reference_transports.<name>`：可复用的参考文件上传目标

当前 `protocol` 支持：

- `openai-videos`
- `unified-video`

## 运行时环境变量覆盖

这些变量可直接写在命令前，仅对当前命令生效，不会写回 `~/.llm/.env` 或 `~/.llm/config.yaml`。

常用变量：

- `CHAT_MODEL`
- `IMAGE_MODEL`
- `AUDIO_MODEL`
- `VIDEO_MODEL`
- `MODEL`
- `BASE_URL`
- `API_KEY`
- `USER_AGENT`

示例：

```bash
CHAT_MODEL=gpt-5.4 llm chat "用更强模型重写这段文案"
IMAGE_MODEL=gemini-2.5-flash-image-preview llm image "生成一张横版海报" -o banner.jpg
BASE_URL=https://gateway.example.com/v1 API_KEY=sk-test CHAT_MODEL=gpt-5.4 llm chat "输出一句自检文本"
BASE_URL=https://gateway.example.com/v1 API_KEY=sk-test IMAGE_MODEL=seedream-4.0 llm image "生成产品主图" -o hero.jpg
```

说明：

- 如果同时设置了 mode 专属变量和 `MODEL`，优先使用 mode 专属变量
- `BASE_URL` 与 `API_KEY` 会覆盖当前命令最终选中 provider 的连接信息
- `USER_AGENT` 用于覆盖请求头中的 User-Agent

## `--model` 的解析规则

传入 `--model` 时，CLI 会先在所有 provider 下查找与该值匹配的模型名或 `alias`。

解析顺序：

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

因此，`--model` 可以有两种用途：

- 选择已在 `config.yaml` 中定义过的模型或 alias
- 临时指定一个未在 `config.yaml` 中显式声明的新模型名

## 常见排查

若命令启动时报错，优先检查：

- `~/.llm/config.yaml` 是否存在且为合法 YAML
- YAML 中引用的 `${ENV_NAME}` 是否都能在当前环境或 `~/.llm/.env` 中找到
- 对应 provider 是否同时声明了 `base_url` 和 `api_key`
- `modes.<mode>.model` 是否能在对应 provider 的 `models` 中找到
- `--model` 或运行时模型变量是否拼写错误
- `BASE_URL` / `API_KEY` 是否把原有 provider 连接信息覆盖成了错误值
- 本机是否已安装 `openai` 与 `pyyaml`
