# gemini-2.5-flash

## 定位

`gemini-2.5-flash` 是通用多模态理解模型，不是图片生成模型，也不是 TTS 模型。

## 官方能力记录

| 能力 | 结论 | 来源 |
|------|------|------|
| 图片输入 | 支持 | Vertex 模型页；Vertex image understanding；Gemini API image understanding |
| 音频输入 | 支持 | Vertex 模型页；Gemini API audio |
| 视频输入 | 支持 | Vertex 模型页；Vertex video understanding；Gemini API video understanding |
| 图片输出 | 不支持 | Vertex 模型页写明 Outputs: Text |
| 音频输出 | 不支持于标准模型页路径 | Vertex 模型页写明 Outputs: Text |

## 关键限制

### 图片输入

- Maximum images per prompt: **3,000**
- Maximum file size per file for inline data or direct uploads through the console: **7 MB**

来源：

- https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/gemini/2-5-flash
- https://docs.cloud.google.com/vertex-ai/generative-ai/docs/multimodal/image-understanding

### 音频输入

- Maximum audio length per prompt: **Approximately 8.4 hours, or up to 1 million tokens**
- Maximum number of audio files per prompt: **1**

来源：

- https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/gemini/2-5-flash
- https://docs.cloud.google.com/vertex-ai/generative-ai/docs/multimodal/audio-understanding

### 视频输入

- Maximum video length with audio: **Approximately 45 minutes**
- Maximum video length without audio: **Approximately 1 hour**
- Maximum number of videos per prompt: **10**

Gemini API 文档同时说明视频可以通过以下方式输入：

- File API
- Cloud Storage / GCS URI
- Inline Data
- YouTube URL

来源：

- https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/gemini/2-5-flash
- https://docs.cloud.google.com/vertex-ai/generative-ai/docs/multimodal/video-understanding
- https://ai.google.dev/gemini-api/docs/video-understanding

## 输出结论

Vertex 官方模型页片段写明：

- Inputs: **Text, Code, Images, Audio, Video**
- Outputs: **Text**

因此，本项目不应把 `gemini-2.5-flash` 记录为图片输出或音频输出模型。

来源：

- https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/gemini/2-5-flash
- https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash

## 与本项目的关系

适合作为：

- `chat -r` 的图片理解模型
- `chat -r` 的音频理解模型
- 后续 `chat -r` 的视频理解模型

不适合作为：

- `llm image` 图片输出模型
- `llm tts` 音频输出模型
