# llmcmd 当前附件提交方式

## 目的

本文档只记录程序当前已经实现的附件提交方式与请求结构，不推断上游模型能力。

## 代码依据

- `src/llm_cli/files.py:21-138`
- `src/llm_cli/messages.py:24-146`
- `src/llm_cli/task.py:88-180`
- `src/llm_cli/api.py:173-371`
- `src/llm_cli/reference_transport.py:97-134`

## 本地附件识别规则

### 图片附件

图片附件通过 `mimetypes.guess_type()` 识别，要求 MIME 以 `image/` 开头。

代码：`src/llm_cli/files.py:21-26`, `45-46`

### 音频附件

音频附件通过 MIME 或扩展名识别，当前显式兼容：

- `.m4a` → `audio/mp4`
- `.mp3` → `audio/mpeg`
- `.wav` → `audio/wav`
- `.ogg` → `audio/ogg`
- `.flac` → `audio/flac`
- `.aac` → `audio/aac`
- `.wma` → `audio/x-ms-wma`
- `.webm` → `audio/webm`

代码：`src/llm_cli/files.py:27-41`, `49-50`

### 视频附件

视频附件通过 MIME 或扩展名识别，当前显式兼容：

- `.mp4` → `video/mp4`
- `.mov` → `video/quicktime`
- `.webm` → `video/webm`
- `.avi` → `video/x-msvideo`
- `.mkv` → `video/x-matroska`
- `.mpeg` → `video/mpeg`
- `.mpg` → `video/mpeg`

代码：`src/llm_cli/files.py`

### 文本附件

文本附件通过 `text/*` MIME 或扩展名白名单识别。白名单包含常见文本、配置、代码、字幕与日志文件。

代码：`src/llm_cli/files.py:53-95`

## 各命令的实际提交方式

## `llm chat`

### 图片附件

图片在 `chat` 模式下会被序列化为 OpenAI 风格内容块：

```json
{
  "type": "image_url",
  "image_url": {
    "url": "data:image/...;base64,..."
  }
}
```

代码：`src/llm_cli/messages.py:36-43`, `106-122`

### 音频附件

音频在 `chat` 模式下会被序列化为 `file` 内容块，`file_data` 为 data URL：

```json
{
  "type": "file",
  "file": {
    "filename": "demo.wav",
    "mime_type": "audio/wav",
    "file_data": "data:audio/wav;base64,..."
  }
}
```

代码：`src/llm_cli/messages.py:24-33`, `113-119`

### 视频附件

视频在 `chat` 模式下会被序列化为 `file` 内容块，`file_data` 为 data URL：

```json
{
  "type": "file",
  "file": {
    "filename": "demo.mp4",
    "mime_type": "video/mp4",
    "file_data": "data:video/mp4;base64,..."
  }
}
```

代码：`src/llm_cli/messages.py`

### 文本附件

文本附件不会作为二进制文件上传，而是直接读为 UTF-8 文本，再包成 `text` 内容块：

```json
{
  "type": "text",
  "text": "[文件: note.md]\n```md\n...\n```"
}
```

代码：`src/llm_cli/messages.py:46-52`, `118-119`

### 结论

`chat` 当前已经支持：

- 图片理解
- 音频理解
- 视频理解
- 文本附件内联

## `llm chat --edit`

`chat_edit` 只接受：

- 图片附件：`image_url`
- 文本附件：内联 `text`

不接受音频附件，也不接受视频附件。

代码：`src/llm_cli/messages.py:86-103`

## `llm image`

### 默认路径：`image_url` 内容块

`image` 模式在默认 `openai-chat-completions` 协议下，把本地图片参考提交为 `image_url` 内容块，URL 使用 data URL：

```json
{
  "type": "image_url",
  "image_url": {
    "url": "data:image/jpeg;base64,..."
  }
}
```

代码：`src/llm_cli/messages.py`

### 远程 URL 路径：`reference_transport`

当 `prepare_reference_resources()` 先把参考图上传到对象存储后，`image` 模式会把该图改为远程 URL：

```json
{
  "type": "image_url",
  "image_url": {
    "url": "https://..."
  }
}
```

代码：`src/llm_cli/task.py:88-99`, `src/llm_cli/reference_transport.py:97-134`, `src/llm_cli/messages.py:55-61`, `132-136`

### `grok2api-image` 兼容路径

当协议为 `grok2api-image` 且参考文件是图片时，同样使用 `image_url + data URL`：

代码：`src/llm_cli/messages.py`

### 视频附件边界

`image` 模式当前显式拒绝视频附件。

代码：`src/llm_cli/messages.py`

### 图片输出请求级字段

`image` 模式还会在请求顶层透传：

```json
{
  "modalities": ["image", "text"],
  "image_config": {
    "image_size": "2K",
    "aspect_ratio": "16:9"
  }
}
```

代码：`src/llm_cli/task.py:120-131`

## `llm tts`

`tts` 当前不接收附件。请求直接走 Gemini `generateContent`：

```json
{
  "model": "gemini-3.1-flash-tts-preview",
  "contents": [{"parts": [{"text": "..."}]}],
  "generationConfig": {
    "responseModalities": ["AUDIO"],
    "speechConfig": {
      "voiceConfig": {
        "prebuiltVoiceConfig": {
          "voiceName": "Kore"
        }
      }
    }
  }
}
```

代码：`src/llm_cli/api.py:339-371`, `src/llm_cli/task.py:133-160`

## `llm video`

### 当前仅支持首帧参考图

`video` 模式的 `-r/--reference` 当前只取第一张，作为 `input_reference` 或 `images` 提交；它不是视频理解输入。

代码：`src/llm_cli/task.py:166-180`

### `openai-videos` 路径

当前会向 `/videos` 提交 `multipart/form-data`：

- 字段：`model`、`prompt`、`seconds`、`size`
- 文件：`input_reference`

代码：`src/llm_cli/api.py:246-265`

### `unified-video` 路径

当前会向 `/video/create` 提交 JSON：

```json
{
  "model": "...",
  "prompt": "...",
  "images": ["https://..."],
  "seconds": 8,
  "size": "720x1280",
  "aspect_ratio": "9:16"
}
```

若没有上传 URL 但本地存在首帧图，则 `images` 会退回为 data URL。

代码：`src/llm_cli/api.py:197-245`

## 当前缺口

当前程序已经支持 `chat -r` 直接提交视频文件做视频理解，当前序列化方式是 OpenAI 兼容 `file` 内容块加 data URL。

当前仍不存在以下能力：

- `chat --edit -r demo.mp4` 的视频附件编辑辅助
- `image -r demo.mp4` 的视频参考输入
- Gemini 原生 `file_data` / `file_uri` 专用请求分支

后续继续扩展时，仍需把新路径增补到本文档，并补充对应的官方能力来源。
