# llm CLI 技术设计

## 概览

本文档面向项目维护者，说明 `shellus-llmcmd` 的核心结构、主要调用链和扩展约束。

项目目标不是封装某一家固定上游，而是提供一个统一的终端入口，把文本、图片、音频和批处理工作流稳定接到 OpenAI 兼容接口上。

## 模块结构

| 路径 | 责任 |
|------|------|
| `src/llm_cli/cli.py` | Click 命令入口，参数定义，命令分发 |
| `src/llm_cli/config.py` | 读取 `~/.config/llm-api/.env`，解析模型与并发配置，创建 OpenAI 客户端 |
| `src/llm_cli/task.py` | 统一任务执行入口，负责把参数转成消息、调用上游、整理输出 |
| `src/llm_cli/messages.py` | 按 `chat / image / audio / chat_edit` 构造消息体 |
| `src/llm_cli/api.py` | 统一调用 `chat.completions.create(stream=True)`，收集文本与图片等流式结果 |
| `src/llm_cli/output.py` | 提取文本/图片结果，处理默认输出路径与 edit diff 应用 |
| `src/llm_cli/batch.py` | 解析 YAML，准备任务规格，并发执行批处理 |
| `src/llm_cli/session.py` | `chat -s/-I` 的 JSONL 会话持久化 |
| `src/llm_cli/files.py` | 读取图片/音频附件并转为 base64 |
| `src/llm_cli/utils.py` | 路径解析、文本读取、通用错误退出 |

## 主调用链

### 单次命令

`cli.py` 中的子命令先做参数校验，再调用 `create_client()` 与 `run_task()`。

```text
Click 子命令
  -> create_client(mode)
  -> run_task(...)
  -> api_call(stream=True)
  -> extract_text_result() / extract_image_result()
  -> 写文件或输出终端
```

### `chat --edit`

`chat --edit` 不直接返回完整文本，而是要求模型输出 `SEARCH/REPLACE` diff blocks，再由 `output.py` 应用到原文件。

```text
chat --edit
  -> task.py 读取目标文件
  -> messages.py 注入 DEFAULT_EDIT_PROMPT
  -> 上游返回 diff blocks
  -> output.py 应用替换
  -> 覆盖原文件或写入新文件
```

### `chat -s/-I`

会话模式仅支持纯文本对话，不与 `-i/-r/--edit` 混用；`--system` 可以参与会话历史管理。

```text
session.py 读取 JSONL
  -> chat 子命令拼接历史消息
  -> run_task(messages=[...])
  -> 结果追加写回 JSONL
```

当用户在 `chat -s ...` 或 `chat -I -s ...` 中提供 `--system` 时，CLI 会先替换会话开头连续的 `system` 消息，再保留后续 `user / assistant / system(运行期提示)` 历史，并将更新后的结果写回 JSONL。

### `batch`

批处理会先把 YAML 规格归一化成统一的 `task_spec`，再复用 `run_task()` 并发执行。

## 配置规则

配置文件位置：

```bash
~/.config/llm-api/.env
```

关键配置项：

| 变量 | 作用 |
|------|------|
| `API_KEY` | 上游鉴权 |
| `BASE_URL` | OpenAI 兼容接口地址 |
| `MODEL` | 通用默认模型 |
| `CHAT_MODEL` | 文本模式优先模型 |
| `IMAGE_MODEL` | 图片模式优先模型 |
| `AUDIO_MODEL` | 音频模式优先模型 |
| `LLM_CONCURRENCY` | 全局并发上限 |
| `OPENAI_CHAT_CONCURRENCY` | 旧版文本并发兼容变量 |
| `OPENAI_IMAGE_CONCURRENCY` | 旧版图片并发兼容变量 |

模型解析优先级在 `config.py` 中按 mode 分开处理：

- `chat`：`CHAT_MODEL` → `MODEL`
- `image`：`IMAGE_MODEL` → `MODEL`
- `audio`：`AUDIO_MODEL` → `MODEL`

交互式内置命令约束：

- `/clear` 清空当前会话；若当前已绑定持久化会话文件，则同步清空文件内容
- `/model <name>` 切换当前交互模型，并写回 `~/.config/llm-api/.env` 中的 `CHAT_MODEL`
- `/save <name-or-path>` 将当前会话整体保存到指定文件；若当前已持久化且目标不同，则切换到新文件继续写入

## 消息构造约束

`messages.py` 是整个项目最敏感的模块之一，任何多模态输入能力都必须经过这里收敛。

当前约束如下：

- `chat` 支持文本 + 多张参考图
- `chat_edit` 支持文本文件内容 + 修改要求 + 可选参考图
- `image` 支持主 prompt + 多张参考图 + 补充文本约束
- `audio` 通过 `file` 类型上传音频，避免依赖不稳定的 `input_audio`

新增输入能力时，优先扩展 `build_messages()`，不要在 `cli.py` 或 `task.py` 拼接临时消息结构。

## 输出处理约束

`output.py` 负责处理两类高风险逻辑：

1. 从响应中提取图片
2. 对 edit 模式执行精确文本替换

维护时注意：

- 图片结果优先读取 `message.images`
- `chat` 模式若检测到图片响应，也按图片结果落盘并返回路径，不再把 base64 当文本输出
- 如果上游返回 Markdown 图片链接，则回退到正则提取并下载
- `chat / image / audio` 请求统一走 `stream=True`
- 非交互 `chat / audio` 必须把流式文本实时写到 stdout，不允许等完整响应后一次性输出
- edit 模式必须保持“唯一定位 + 最小修改”，不能放宽 SEARCH 匹配规则

## 扩展建议

### 新增命令

如果要增加新子命令，优先遵循现有分层：

1. 在 `cli.py` 定义参数和帮助信息
2. 在 `config.py` 定义该 mode 的模型解析规则
3. 在 `messages.py` 增加消息构造
4. 在 `task.py` 接入执行与结果整理
5. 在 `tests/` 添加 CLI 透传测试和消息构造测试

### 新增输入参数

新增参数时优先判断它属于哪一层：

- CLI 入口参数：放 `cli.py`
- 文件读取与归一化：放 `task.py`
- 最终消息协议：放 `messages.py`

不要把某个模式特有的临时拼接逻辑散落到多个文件中。

## 发布流程

建议发布顺序：

1. 修改版本号 `src/llm_cli/__init__.py`
2. 运行测试
3. 执行构建
4. 检查 `git diff` 与提交信息
5. push 到远端
6. 发布到 PyPI

## 已知维护点

- 当前测试集中在 `tests/test_chat_session.py`，覆盖范围仍偏窄，后续应拆分出 `image`、`batch`、`output` 的独立测试文件
- `README.md` 目前承担了安装、使用、配置、部分行为说明，后续可以继续下沉到 `docs/features/`
- `pyproject.toml` 的 `readme` 目前指向 `SKILL.md`，如果未来对 PyPI 展示要求更高，可以考虑改回更面向用户的 `README.md`
