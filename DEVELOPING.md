# Developing shellus-llmcmd

本文件面向准备修改本项目代码的人。

目标不是逐文件索引源码，而是用尽量短的篇幅说明：

- 这个项目解决什么问题
- 代码大致怎么组织
- 哪些设计边界是故意的
- 文档应该怎么分工，避免重复

## 项目定位

`shellus-llmcmd` 是一个统一的 LLM 命令行入口。

它的核心目标是：

- 用一条 `llm` 命令统一承载 `chat / image / audio / video / batch`
- 保持终端友好，方便脚本、自动化和 AI Agent 调用
- 通过 OpenAI 兼容接口接入不同上游，而不是在 CLI 内绑定某一家厂商 SDK

当前项目优先服务两类使用者：

- 人类用户：希望在终端里稳定调用文本、图片、音频、视频和批处理能力
- AI Agent：希望通过 `README.md` 或 `SKILL.md` 获取完整使用说明，并快速定位调用方式

## 核心架构

主调用链保持简单：

```text
cli.py
  -> config.py
  -> pi_agent.py
  -> task.py
  -> messages.py / api.py
  -> output.py
```

各模块职责如下：

- `src/llm_cli/cli.py`
  负责命令入口、参数定义和基础校验
- `src/llm_cli/config.py`
  负责读取 `~/.llm/{.env,config.yaml}`，构建运行时配置实例，创建 OpenAI 客户端，并解析 provider、模型与并发配置
- `src/llm_cli/pi_agent.py`
  负责把当前 `chat` 配置桥接为 `pi` 可消费的 `models.json` 与启动参数
- `src/llm_cli/task.py`
  负责统一组织一次任务执行，把 CLI 参数转成消息或请求级元数据，再调用上游
- `src/llm_cli/messages.py`
  负责消息内容本身的构造，是多模态输入的核心收口点
- `src/llm_cli/reference_transport.py`
  负责按配置把参考文件预处理为可直接提供给上游的 URL
- `src/llm_cli/api.py`
  负责统一调用 `chat.completions.create(stream=True)` 并收集流式结果
- `src/llm_cli/output.py`
  负责文本和图片结果提取、落盘以及 edit diff 应用
- `src/llm_cli/batch.py`
  负责 YAML 批处理归一化与并发执行
- `src/llm_cli/session.py`
  负责 `chat -s/-I` 的 JSONL 会话持久化

## 关键设计边界

### 统一走 OpenAI 兼容入口

项目当前刻意保持 `chat / image / audio` 共用 OpenAI 兼容入口，不在 CLI 内为 Gemini、Claude、OpenAI 等分别维护多套 SDK 调用路径。

这样做的原因：

- 降低命令层复杂度
- 保持配置入口统一
- 复用同一套流式处理与输出提取逻辑
- 让后端兼容层承担 provider 协议转换

### `agent` 是桥接能力，不是 `chat -I` 的替代实现

`llm agent` 当前是对外部 `pi` coding agent 的桥接入口。

实现时保持以下边界：

- 不要把 `chat -I` 直接替换成 `pi`
- `agent` 复用当前 `chat` 模式的 `base_url`、`api_key` 与模型名
- `agent` 的会话格式、工具语义和交互行为由 `pi` 自己负责，不与 `session.py` 的 JSONL 兼容性绑定
- 真实 API key 只通过子进程环境变量传递，不写入 `models.json`

### 消息内容和请求级元数据要分开

修改功能时需要先判断参数属于哪一层：

- 如果它属于“消息内容”，例如 prompt、参考图、文本附件，应优先落在 `messages.py`
- 如果它属于“请求顶层控制字段”，例如 `modalities`、`image_config`，应通过 `task.py -> api.py` 透传

不要把协议级能力伪装进 prompt 或 system 文本。

当前还要保持一个具体约束：

- `chat` 模式下，文本类参考输入优先转为内联文本，图片类参考输入作为图片输入；不要重新引入依赖不稳定附件兼容行为的实现

### image 的 size/aspect 支持边界

`image --size/--aspect` 当前采用 OpenAI 风格顶层 `image_config` 透传。

本项目当前只明确承诺它在 `cliproxy -> Gemini` 相关链路中有效，不假设其他 OpenAI 兼容后端会做同等适配。

因此：

- `size/aspect` 是图片能力的通用语义
- 但当前落地支持范围仍以 Gemini 兼容链路为主

## 修改代码时的判断原则

### 新增命令

优先沿用现有分层：

1. 在 `cli.py` 定义参数
2. 在 `task.py` 接执行
3. 在 `messages.py` 或 `api.py` 接协议
4. 在 `output.py` 接结果
5. 在测试里补 CLI 透传和行为验证

### 新增参数

先判断它是：

- CLI 参数
- 消息内容
- 请求级元数据
- 输出行为控制

不要把一个参数的处理逻辑散到多个文件里各写一半。

### 修改高风险模块

以下模块修改时要特别谨慎：

- `messages.py`
  这里是多模态输入协议的核心收口点
- `output.py`
  这里处理图片提取和 edit diff，容易出现行为回归
- `session.py`
  这里影响持久会话兼容性
- `batch.py`
  这里容易出现单命令和批处理行为不一致

## 文档分工

项目内文档按下面的边界维护。

### README.md

定位：项目主文档，也是完整使用说明之一。

负责：

- 这是什么
- 有什么特色
- 怎么安装
- 完整命令说明
- 参数
- 示例
- YAML 编排
- 边界和注意事项

### SKILL.md

定位：Agent 优先阅读的完整使用手册。

负责：

- 说明这个项目适合什么任务
- 给出完整命令说明、参数、示例和配置方式
- 保留适合 Agent 快速扫描的入口信息
- 与当前 CLI 行为保持一致，不得长期保留过期说明

### 开发参考文档

定位：给准备修改代码的人快速建立正确心智。

本文件承担这个角色，不重复维护命令参数手册内容。

## 文档维护规则

- `README.md` 和 `SKILL.md` 都必须维护为完整使用手册
- 新增、删除或调整 CLI 用法时，`README.md` 与 `SKILL.md` 必须同步更新
- `SKILL.md` 可以更强调 Agent 入口和终端自动化视角，但命令能力、参数范围、配置方式不得与 `README.md` 脱节
- 如果两份手册在组织方式上不同，应保证事实一致，而不是一处更新、另一处滞后
- 如果需要记录实现原因、兼容边界和架构取舍，放在开发参考文档或专题设计文档中，而不是塞进使用手册

## 相关文档

- 项目主文档：[`README.md`](./README.md)
- Agent 使用手册：[`SKILL.md`](./SKILL.md)
- 配置说明：[`CONFIGURATION.md`](./CONFIGURATION.md)
- 历史专题设计文档：[`docs/dev-spec/`](./docs/dev-spec/)
