# gemini-3.1-flash-tts-preview

## 定位

`gemini-3.1-flash-tts-preview` 是文本转语音模型，用于输出音频，不是通用图像或视频理解模型。

## 官方能力记录

| 能力 | 结论 | 来源 |
|------|------|------|
| 文本输入 | 支持 | Gemini API 模型页；speech generation |
| 音频输出 | 支持 | Gemini API 模型页；speech generation |
| 单人语音 | 支持 | speech generation |
| 多人语音 | 支持 | speech generation |
| 图片输出 | 不支持 | 文档仅记录语音生成 |

## 关键限制与请求方式

- Input token limit: **8,192**
- Output token limit: **16,384**
- Audio generation: **Supported**
- 生成单人语音时，需要把 `response modality` 设为 `audio`
- 可通过 `SpeechConfig -> VoiceConfig -> prebuiltVoiceConfig.voiceName` 指定音色
- 官方示例直接使用 `voiceName: Kore`

来源：

- https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-tts-preview
- https://ai.google.dev/gemini-api/docs/speech-generation

## 结论

`gemini-3.1-flash-tts-preview` 可以被记录为本项目当前的音频输出模型。

本项目当前 `tts` 实现与官方示例一致，走的是 `generateContent + responseModalities=["AUDIO"]` 路径，而不是 Live API。

## 与本项目的关系

当前代码路径：

- `src/llm_cli/api.py:339-371`
- `src/llm_cli/task.py:133-160`

当前程序会：

1. 向 `:generateContent` 发送文本 prompt
2. 在 `generationConfig` 中声明 `responseModalities=["AUDIO"]`
3. 可选传入 `voiceName`
4. 从响应的 `inlineData` 取回 PCM 数据并封装为 wav

## 补充说明

Vertex AI 另有 `Gemini Live API` 路径可输出音频，例如 `gemini-2.5-flash-live-api` 模型页写明 `Outputs: Text, Audio`。

该路径属于实时音视频会话能力，不应与本项目当前 `tts` 的离线生成路径混写。

来源：

- https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/gemini/2-5-flash-live-api
