# gemini-2.5-flash-image

## 定位

`gemini-2.5-flash-image` 是图片理解与图片生成模型。

## 官方能力记录

| 能力 | 结论 | 来源 |
|------|------|------|
| 图片输入 | 支持 | Vertex 模型页 |
| 图片输出 | 支持 | Vertex 模型页 |
| 音频输入 | 本次未记录 | - |
| 视频输入 | 本次未记录 | - |
| 音频输出 | 不支持 | Vertex 模型页写明 Outputs: Text and image |

## 关键限制

- Inputs: **Text, Images**
- Outputs: **Text and image**
- Maximum images per prompt: **3**
- Maximum file size per file for inline data or direct uploads through the console: **7 MB**
- Maximum file size per file from Google Cloud Storage: **30 MB**
- Maximum number of output images per prompt: **10**
- Supported aspect ratios: **1:1, 3:2, 2:3, 3:4, 4:3, 4:5, 5:4, 9:16, 16:9, 21:9**

来源：

- https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/gemini/2-5-flash-image

## 结论

`gemini-2.5-flash-image` 可以被记录为图片输出模型。

本项目在维护文档、默认模型说明与能力判断时，应把图片输出能力限定在 `-image` 模型上，而不是泛化到 `gemini-2.5-flash` 这类通用理解模型。

## 与本项目的关系

适合作为：

- `llm image` 的图片输出模型
- 图片编辑与多参考图生成模型

不适合作为：

- `llm tts` 音频输出模型
