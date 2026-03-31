# shellus-llmcmd

**一个统一的 LLM 命令行工具。**

用一条 `llm` 命令，把日常 AI 工作流收敛到终端里：

- 写文案、总结、翻译、提取结构化数据
- 根据参考图生成或修改图片
- 把音频转成文本或 SRT 字幕
- 用 YAML 一次编排多条 chat / image / audio / video 任务
- 直接在终端里按要求编辑文本文件
- 用 JSONL 持久化 `chat` 会话，并在终端里连续对话

如果你希望把 LLM 能力稳定地接进 shell 脚本、自动化任务、个人工具链，而不是在多个网页和客户端之间切换，`shellus-llmcmd` 就是为这种场景准备的。

## 为什么用它

- **一个命令统一入口**：`chat`、`image`、`audio`、`batch`
- **终端友好**：天然适合 shell、cron、CI、脚本拼装
- **文件编辑能力**：`chat --edit` 直接按要求改文件
- **多图生成能力**：`image -n` 支持数量控制、并发控制和轻量进度输出
- **批处理能力**：YAML 一次组织多条任务
- **兼容 OpenAI 风格接口**：适合自建网关、代理层、兼容服务

## 安装

```bash
pip install shellus-llmcmd
```

安装后命令名是：

```bash
llm
```

## 使用场景

### 1. 直接生成文本

```bash
llm chat "写一段产品介绍"
llm chat @prompt.txt -o result.md
llm chat "总结重点" -r article.md -r notes.pdf
llm chat "继续上一轮结论" -s worklog
llm chat -I -s worklog
```

### 2. 直接修改文件

```bash
llm chat "把人物脸型改成偏瘦，不要改动其他描述" --edit prompt.md
llm chat "按要求改写" --edit prompt.md -o prompt.v2.md
```

### 3. 结合图片理解来写提示词

```bash
llm chat "详细描述这张图的所有细节" -r photo.jpg
llm chat "总结这个附件的重点" -r report.docx
llm chat "对比两张参考图后总结共同特征" -r photo-a.jpg -r photo-b.jpg
llm chat "根据参考图修正人物外貌描述" --edit prompt.md -r ref.jpg
```

### 4. 一次生成多张图片

```bash
llm image "生成三张海报方案" -n 3 -o poster.jpg
llm image "融合两张参考图的风格生成情侣自拍" -r person.jpg -r style.jpg -o couple.jpg
llm image @prompt.md -r person.jpg -r constraints.pdf -o result.jpg
llm image @prompts/couple-photo.md -r refs/person-a.jpg -r refs/person-b.jpg -o outputs/couple-photo/result.jpg -n 4
llm image "生成横版海报" --size 2K --aspect 16:9 -o banner.jpg
```

输出结果示例：

- `poster.jpg`
- `poster_1.jpg`
- `poster_2.jpg`

### 5. 音频转录或总结

```bash
llm audio "总结录音内容" -r demo.m4a
llm audio -r demo.m4a
llm audio "请输出标准 SRT 字幕" -r demo.m4a -o demo.srt
```

### 6. 视频生成

```bash
llm video "生成一段海边航拍视频"
llm video "生成产品展示短片" -r first-frame.jpg --seconds 8 --size 720x1280 -o demo.mp4
llm video --resume vid_123 -o demo.mp4
```

说明：

- `video` 默认先创建异步任务，再持续等待完成并自动下载
- 创建成功后会先打印任务 ID，便于中断后用 `--resume` 恢复
- `-r/--reference` 当前用于上传首帧参考图，仅使用第一张

### 7. YAML 批量编排

```bash
llm batch tasks.yaml
```

示例：

```yaml
mode: chat
system_prompt: "你是严谨的处理助手"
output_dir: outputs

tasks:
  - id: summary
    prompt: "总结下面内容"
    input: article.md
    output: summary.md

  - id: edit-prompt
    prompt: "把人物脸型改成偏瘦，不要改动其他描述"
    edit: 商务女性生图.md
    output: 商务女性生图.v2.md

  - id: hero-image
    mode: image
    prompt: "为产品主页生成三张极简横幅图"
    count: 3
    size: 2K
    aspect: "16:9"
    output: hero.jpg

  - id: transcript
    mode: audio
    audio_file: meeting.mp3
    prompt: "请输出标准 SRT 字幕"

  - id: promo-video
    mode: video
    prompt: "生成一段产品宣传短片"
    reference:
      - cover.jpg
    seconds: "8"
    size: 720x1280
    output: promo.mp4
```

## 命令速览

### `llm chat`
用于文本生成、分析、问答、改写、持久对话，以及 `--edit` 文件编辑。
`@文件` 用于把文本直接读进 prompt；`-r/--reference` 用于提供参考附件，其中图片按 `image_url` 发送，文本附件会先内联为文本内容块。

新增会话参数：

- `-s/--session`：加载并持久化对话历史，值可为会话名或 `.jsonl` 路径
- `-I/--interactive`：进入交互式连续对话；默认仅保存在内存中，配合 `-s` 才会加载并持久化

示例：

```bash
llm chat "总结上次方案并继续补充" -s product-review
llm chat -I
llm chat -I "你是什么模型？"
llm chat -I -s ./sessions/product-review.jsonl
```

说明：

- `-s product-review` 会落盘到当前目录下的 `product-review.jsonl`
- 单次模式和 `-I -s ...` 交互模式可共享同一个会话文件，随时切换继续
- `llm chat -I "首轮问题"` 会先发送这条首轮消息，再进入连续对话
- `-I` 模式下只有配合 `-s` 才会回放历史消息并持续写回；不带 `-s` 时为纯内存会话
- `-I` 基于 `Textual` 全屏 TUI 提供消息区、输入区、输入框上方常驻交互状态行和底部元信息栏
- 交互输入区支持多行粘贴与手动换行；`Enter` 发送，`Shift+Enter` 或 `Ctrl+J` 换行
- 历史消息中的 `你 / AI / 系统` 角色标签会独立着色，便于快速分辨不同轮次
- 当前持久会话先聚焦连续文本对话，不与 `-r/--edit` 组合
- `chat -s ... --system ...` 与 `chat -I -s ... --system ...` 会把 system prompt 写入会话历史；再次带 `--system` 启动同一会话时，只会覆盖会话开头连续的 system 消息，其余历史保留
- 交互式内置命令：`/clear` 清空当前会话，`/model <name>` 切换当前模型并写回 `~/.llm/.env` 中的 `CHAT_MODEL`，`/save <name-or-path>` 将当前会话保存到指定文件
- 如需使用终端原生鼠标拖选复制历史消息，请按住终端模拟器的修饰键；当前环境实测为按住 `Shift` 再拖选
- `chat` / `image` / `audio` 当前统一通过流式请求收集结果
- 非交互 `chat` 与 `audio` 会实时把流式文本写到 stdout
- 若 `chat` 使用图片模型并返回图片，会自动落盘并显示图片路径

### `llm image`
用于图片生成或参考图编辑，支持 `-n/--count` 多图生成。`-r/--reference` 用于上传附件，当前统一走 `type=file`。

补充说明：

- `--size` 支持 `512 / 1K / 2K / 4K`
- `--aspect` 支持 `1:1 / 16:9 / 9:16 / 4:3 / 3:4 / 3:2 / 2:3 / 4:5 / 5:4 / 21:9`
- `--size` 和 `--aspect` 的实际生效情况取决于你所使用的图片后端
- batch YAML 中的 `aspect` 建议写成带引号的字符串，例如 `"16:9"`，避免 YAML 误解析

### `llm audio`
用于把音频送入模型处理，位置参数是 prompt，`-r/--reference` 上传音频附件；默认实时输出到 stdout，仅在传 `-o` 时写文件。若要 SRT，请直接在 prompt 中明确要求。

### `llm video`
用于异步视频生成。默认会创建任务、等待完成并自动下载，也支持通过 `--resume <task_id>` 恢复等待并下载。

补充说明：

- `--seconds` 支持 `4 / 8 / 12 / 16 / 20`
- `--size` 当前支持 `720x1280 / 1280x720 / 1024x1024`
- `-r/--reference` 当前仅取第一张图作为 `input_reference`
- 下载固定走 `GET /v1/videos/{id}/content`

### `llm batch`
用于 YAML 批量任务编排。

## 配置

`shellus-llmcmd` 默认从以下位置读取配置：

```bash
~/.llm/.env
~/.llm/config.yaml
```

配置来源、优先级、`--model` 解析规则、运行时环境变量覆盖，以及完整示例，见：

- [CONFIGURATION.md](./CONFIGURATION.md)

最常见的临时覆盖方式：

```bash
CHAT_MODEL=gpt-5.4 llm chat "用更强模型重写这段文案"
BASE_URL=https://gateway.example.com/v1 API_KEY=sk-test llm chat "输出一句自检文本"
```

## 包信息

- PyPI 包名：`shellus-llmcmd`
- CLI 命令名：`llm`
- Python 要求：`>=3.10`

## 相关文档

- AI Agent 入口文档：[SKILL.md](./SKILL.md)
- 配置说明：[CONFIGURATION.md](./CONFIGURATION.md)
- 开发参考：[DEVELOPING.md](./DEVELOPING.md)
