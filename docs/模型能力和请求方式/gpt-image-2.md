# 仅支持 Responses API 的图片模型协议说明

## 适用范围

本文说明的是一类**通过 OpenAI Responses API 返回图片结果**的模型接入方式，而不是某个特定网关或某个特定中转站的私有实现。

这类模型的共同特点通常是：

- 请求入口不是 `/v1/images/generations`
- 请求入口也不是 `chat.completions`
- 必须走 `POST /v1/responses`
- 必须使用 `stream=true`
- 图片结果不在普通文本增量里，而是在工具输出项中返回

`codex/gpt-image-2` 只是这种模型的一种代表性用法。对 `llmcmd` 来说，真正重要的是这类模型的**协议形态**，而不是背后接入了哪一个具体网关。

## 对 `llmcmd` 的意义

`llmcmd` 作为客户端，不应关心服务端是如何把某个模型封装成图片模型的。

`llmcmd` 只需要识别下面这件事：

- 当前图片模型属于 `openai-responses` 协议

一旦模型在配置中声明：

```yaml
protocol: openai-responses
```

`llmcmd` 就应按 Responses 图片协议处理，而不是按传统图片接口或 `chat.completions` 处理。

## 协议结论

这类图片模型当前应按以下方式调用：

1. **必须使用** `POST /v1/responses`
2. **必须使用** `stream: true`
3. **必须按 SSE** 读取流式事件
4. 最终图片结果位于 `response.output_item.done.item.result`
5. `item.result` 通常为 base64 图片数据

常见不适用方式如下：

- `POST /v1/chat/completions`
- `POST /v1/images/generations`
- `POST /v1/responses` 且 `stream: false`

## 最小请求结构

对这类模型，最小可用请求通常如下：

```json
{
  "model": "<image-model>",
  "input": [
    {
      "role": "user",
      "content": "画一只可爱的猫抱着水獭"
    }
  ],
  "stream": true
}
```

说明：

- `model` 由具体部署决定，例如 `codex/gpt-image-2`
- `input` 使用 Responses 风格，而不是 `messages`
- `stream` 必须为 `true`
- 是否需要显式传 `tools`，取决于所接入服务端的实现；`llmcmd` 不应把某个私有网关的注入逻辑写死到通用说明里

## 请求结构体

对 `llmcmd` 而言，可按如下最小结构理解请求体：

```python
class OpenAIResponsesImageRequest(TypedDict, total=False):
    model: str
    input: list[dict] | str
    instructions: str
    stream: bool
    metadata: dict
    user: str | dict
```

推荐字段说明如下：

| 字段 | 是否必需 | 说明 |
| --- | --- | --- |
| `model` | 是 | 具体模型名，例如某个图片模型别名 |
| `input` | 是 | 用户输入，建议传标准 Responses `input` 结构 |
| `stream` | 是 | 必须为 `true` |
| `instructions` | 否 | 可选系统或附加指令 |
| `metadata` | 否 | 业务透传元数据 |
| `user` | 否 | 业务用户标识 |

## 流式响应事件

这类模型返回的是 `text/event-stream`，每个事件形如：

```text
event: <event_name>
data: <json>
```

实测常见关键事件包括：

- `response.created`
- `response.in_progress`
- `response.output_item.added`
- `response.image_generation_call.in_progress`
- `response.image_generation_call.generating`
- `response.image_generation_call.partial_image`
- `response.output_item.done`
- `response.content_part.added`
- `response.output_text.done`
- `response.content_part.done`
- `response.completed`
- `[DONE]`

并不是所有服务端都会返回完全相同的事件集合，但图片结果的提取原则应保持一致。

## 响应结构体

对客户端结果提取而言，可按如下最小结构处理：

```python
class ResponsesOutputItem(TypedDict, total=False):
    type: str
    id: str
    status: str
    role: str
    content: list[dict]
    quality: str
    size: str
    result: str
    revised_prompt: str


class ResponsesStreamEvent(TypedDict, total=False):
    type: str
    response: dict
    item: ResponsesOutputItem
    delta: str
    output_index: int
    content_index: int
    item_id: str
```

对这类图片模型来说，真正决定图片结果的不是普通文本增量，而是工具输出项。

## 最终图片结果位置

最终图片结果通常出现在：

```json
{
  "type": "response.output_item.done",
  "item": {
    "type": "image_generation_call",
    "status": "completed",
    "quality": "auto",
    "size": "auto",
    "result": "<base64-image>",
    "revised_prompt": "..."
  }
}
```

关键字段说明：

- `item.type == "image_generation_call"` 表示这是生图工具返回项
- `item.result` 是最终图片的 base64 数据
- `item.revised_prompt` 是上游修订后的提示词
- `item.quality`、`item.size` 适合写入调试日志

## 完成事件中的辅助信息

结束时通常还会出现 `response.completed`。其中常见可用字段包括：

- `response.model`：服务端实际运行的模型名
- `response.tools`：本次请求中实际启用的工具信息
- `response.usage`：整体 token 使用
- `response.tool_usage`：工具级使用统计

这些字段适合用于调试、审计或成本分析，但图片落盘不应依赖它们。

## `llmcmd` 的处理要求

`llmcmd` 对接这类模型时，应遵守以下规则：

1. 模型配置中声明 `protocol: openai-responses`
2. 请求路径走 `/v1/responses`
3. 请求体固定带 `stream=true`
4. 响应按 SSE 读取，而不是按单个完整 JSON 读取
5. 图片提取点固定为 `response.output_item.done.item.result`
6. 文件落盘默认按 `.png` 处理

这意味着：

- `llmcmd` 处理的是一种**协议类型**
- 不是针对某个单独网关做硬编码适配

## 建议的提取顺序

建议的客户端处理顺序如下：

1. 逐条读取 SSE 的 `data:` 负载
2. JSON 解析每条事件
3. 过滤出 `type == "response.output_item.done"`
4. 检查 `item.type == "image_generation_call"`
5. 读取并解码 `item.result`
6. 落盘为 `png`
7. 继续读取到 `response.completed` 或 `[DONE]`

## 成功判定

一次成功的 Responses 图片请求，至少满足以下条件：

- HTTP 状态码为 `200`
- 流中出现 `response.output_item.done`
- 该事件中的 `item.type == "image_generation_call"`
- `item.result` 为非空 base64 字符串
- 后续出现 `response.completed` 或 `[DONE]`

## curl 联调示例

```bash
curl -N '<BASE_URL>/v1/responses' \
  -H 'Authorization: Bearer <API_KEY>' \
  -H 'Content-Type: application/json' \
  -H 'Accept: text/event-stream' \
  --data '{
    "model": "<image-model>",
    "input": [
      {
        "role": "user",
        "content": "画一只可爱的猫抱着水獭"
      }
    ],
    "stream": true
  }'
```

## 一句话结论

**对 `llmcmd` 来说，这类模型的本质不是某个具体网关里的特殊模型，而是一种固定走 `/v1/responses` + `stream=true`，并要求从 `response.output_item.done.item.result` 提取最终图片的图片协议。**
