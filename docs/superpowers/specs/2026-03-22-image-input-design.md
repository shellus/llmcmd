# Image Input Design

**日期：** 2026-03-22

## 目标

让 `llm image` 支持通过 `-i/--input` 传入一个或多个文本文件，作为图片生成或改图时的补充约束；`prompt` 继续保留为主修改意图。

## 设计

### 接口语义

- `prompt`：主修改意图，说明“要改成什么”
- `-r/--reference`：图片参考，可重复传入
- `-i/--input`：文本约束文件，可重复传入，说明“不要改什么”或“额外要求”
- `-s/--system`：系统级约束，不作为日常补充提示词主入口

### 数据流

`image` 子命令读取 `-i/--input` 的文本文件内容，并沿用现有 `read_input_files` 与 `build_messages` 拼装路径，把补充文本和主 `prompt` 合并成一个文本段，再与参考图一起发给模型。

### 约束

- `-i/--input` 在 `image` 模式下只接受文件路径，不接受直接文本
- 不新增 `--append-prompt`，避免和 `prompt`、`system` 形成重叠
- 保持 `chat` 的 `-i` 语义一致，减少学习成本

### 测试

- CLI 层验证 `image -i` 会把输入文件传给 `run_task`
- 消息构造层验证 `image` 模式会把 `prompt` 和输入文件内容共同写入文本消息

## 成功标准

- `llm image @prompt.md -i constraint.md -r ref.jpg` 可正常执行
- `-i` 文本内容会进入图片请求
- 现有测试无回归
