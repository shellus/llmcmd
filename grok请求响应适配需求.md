# Grok 请求响应适配需求

## 背景

- `https://grok.jjcc.fun/v1` 指向当前这套自部署服务。
- 这套部署对接的是 Grok 网页版的逆向请求，不是官方公开 API。
- Grok 网页版的逆向（grok2api）部署路径:/data/compose/grok2api，它的代码路径：/data/compose/grok2api/grok2api
- 当前 `llmcmd` 的 `image` 模式实现，实际走的是 OpenAI 风格的 `POST /v1/chat/completions`。

## 测试参数

用于联调和回归测试的固定参数如下：

| 项目 | 值 |
| --- | --- |
| Base URL | `https://grok.jjcc.fun/v1` |
| API Key | `gr-pie4oJahbojuof7e` |
| 文本可用模型示例 | `grok-4.1-fast` |
| 图片模型 | `grok-imagine-1.0` |
| 图片编辑模型 | `grok-imagine-1.0-edit` |
| 视频模型 | `grok-imagine-1.0-video` |


## 重要提醒

- 如果请求出现 `403`，有可能只是上游逆向渠道不稳定，或当前 Cloudflare / 逆向链路暂时异常；不要轻易武断认为一定是请求格式有问题，可以交叉测试一下chat模型是否正常，一般chat正常则服务正常，chat不正常，说明是上游或者逆向稳定性问题，可以重试或者停下来等待用户处理

## 图像接口分类

目前图片生成常见有三类接口：

1. `dalle` 风格：`/v1/images/generations`
2. `openai` 聊天风格：`/v1/chat/completions`
3. `gemini` 风格：`/v1beta/models/<modelName>:generateContent`

当前 `llmcmd` 的图片实现，实测走的是第 2 类，也就是 OpenAI 聊天风格的 `POST /v1/chat/completions`。

其中dalle又在某些情况下是一个生成编辑区分开的变种：
image-generation：/v1/images/generations
image-edits：/v1/images/edits

我也不知道应该怎么来搞这个。
我希望确认如果grok-imagine-1.0可以走/v1/images/generations接口实现生成和编辑（参考图生成），那我们就不用实现很不优雅的generations/edits两个接口+两个模型定义了。

## 本次确认结论

### 1. `llmcmd` 使用 `grok-imagine-1.0` 当前不能成功生成图片

实测命令语义：

```bash
BASE_URL=https://grok.jjcc.fun/v1 \
API_KEY=gr-pie4oJahbojuof7e \
IMAGE_MODEL=grok-imagine-1.0 \
llm image "请为我生成一张图片：雨夜东京街头，一名年轻女性站在便利店门口，穿深色风衣，手里拿着透明雨伞，路面有霓虹倒影，写实摄影风格。" \
  --model grok-imagine-1.0 \
  --debug
```

表现：

- `llmcmd` 发起的是 `POST /v1/chat/completions`
- 服务端没有返回参数校验错误
- `llmcmd` 最终报错：`未在响应中提取到图片`

可见的调试信息：

```text
[DEBUG] 请求方法: POST
[DEBUG] 请求 URL: https://grok.jjcc.fun/v1/chat/completions
[DEBUG] 请求参数: {
  "model": "grok-imagine-1.0",
  "messages": [
    {
      "role": "user",
      "content": "请为我生成一张图片：雨夜东京街头，一名年轻女性站在便利店门口，穿深色风衣，手里拿着透明雨伞，路面有霓虹倒影，写实摄影风格。"
    }
  ],
  "stream": true
}
[DEBUG] 流式收集 content: ''
[DEBUG] 流式收集 images: None
Error: 未在响应中提取到图片
```

当前判断：

- 这不能直接说明 `grok-imagine-1.0` 模型不可用。
- 更像是请求已进入图片链路，但 `llmcmd` 当前的响应提取方式没有拿到图片结果。

### 2. `llmcmd` 使用 `-r` 当前不能成功编辑图片

这里实际测试的是图片编辑模型 `grok-imagine-1.0-edit`，因为服务端编辑模型就是它。

实测命令语义：

```bash
BASE_URL=https://grok.jjcc.fun/v1 \
API_KEY=gr-pie4oJahbojuof7e \
IMAGE_MODEL=grok-imagine-1.0-edit \
llm image "请为我编辑这张图片：保留主体构图，把画面改成白天的城市街道场景，人物站立，写实摄影风格。" \
  --model grok-imagine-1.0-edit \
  -r ./ref.png \
  --debug
```

表现：

- `llmcmd` 同样发起的是 `POST /v1/chat/completions`
- 服务端直接返回参数错误

服务端返回的明确错误：

```text
file.file_data base64 must be provided as a data URI (data:<mime>;base64,...)
```

当前判断：

- 这个失败不是“模型不存在”
- 而是 `llmcmd` 当前发送的附件格式，与该服务端要求不一致

### 3. `grok-imagine-1.0-video` 可以成功创建视频任务

实测命令语义：

```bash
BASE_URL=https://grok.jjcc.fun/v1 \
API_KEY=gr-pie4oJahbojuof7e \
VIDEO_MODEL=grok-imagine-1.0-video \
llm video "生成一段写实短视频：雨夜城市街头，一名年轻女性手持透明雨伞缓慢向前走，路面有霓虹倒影，镜头平稳推进。" \
  --model grok-imagine-1.0-video \
  --seconds 6 \
  --size 720x1280 \
  --debug
```


`llmcmd` 可见输出：

```text
任务 ID: video_3b3b1dd69bbd41129991463d
```

服务端日志中可见：

```text
Media post created: 66e8818d-8952-4c36-be1e-846930fb7fea (type=MEDIA_POST_TYPE_VIDEO)
```

当前判断：

- 视频模型入口是可用的
- 至少“创建任务”这一步没有问题
- 这次没有继续等到最终下载完成，因此还不能据此断言“视频全流程已经完全兼容”

## 对 `llmcmd` 的适配建议

### 优先级 1：确认图片模式到底要走哪条协议

当前 `llmcmd image` 实现，走的是 `POST /v1/chat/completions`。

需要明确：

- 是否继续沿用 `openai/chat.completions` 风格，让服务端在聊天流里返回图片
- 还是针对这类服务，增加单独的图片协议，改走 `POST /v1/images/generations`

当前现状下，`llmcmd` 通过聊天流提取图片的方式，至少对这套 Grok 部署还不稳定。

### 优先级 2：修正图片编辑附件格式

服务端要求图片编辑的附件数据是 Data URI：

```text
data:<mime>;base64,...
```

当前 `llmcmd` 发送的不是这个格式，因此会被服务端直接拒绝。

### 测试注意事项：视频时长

对这套服务，视频时长需要满足：

```text
6 <= seconds <= 30
```

这是 `grok2api` 当前上游接口或当前模型能力边界，不在 `llmcmd` 代码中处理。

`llmcmd` 只需要把上游返回的错误原样抛出，不要掩盖或擅自改写。
