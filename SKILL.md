---
name: llm
description: Use when text generation, image generation or editing, audio transcription, or mixed YAML orchestration tasks need to be handled through one unified CLI entry.
---

# llm skill

这个 skill 对应项目里的统一命令行入口 `llm`。

适用场景：

- 生成一段文本、润色文案、总结资料
- 根据参考图生成或修改图片
- 转录音频或生成字幕
- 用 YAML 批量执行 `chat / image / audio`
- 按要求直接编辑文本文件

## Agent 使用方式

如果你是 AI Agent：

1. 先阅读 [`README.md`](./README.md)
2. 按 README 中的完整命令说明、参数、边界和示例执行
3. 不要把本文件当成完整手册

如果需要远程安装或读取本项目 skill，可直接使用：

```text
https://github.com/shellus/llmcmd/raw/refs/heads/master/SKILL.md
```

## 最常用命令

```bash
llm chat "写一段产品介绍"
llm chat "把人物脸型改成偏瘦" --edit prompt.md
llm image "生成横版海报" --size 2K --aspect 16:9 -o banner.jpg
llm audio "请输出标准 SRT 字幕" -r demo.m4a -o demo.srt
llm batch tasks.yaml
```

## 文档入口

- 完整使用说明：[`README.md`](./README.md)
- 开发参考：[`DEVELOPING.md`](./DEVELOPING.md)
