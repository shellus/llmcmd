# shellus-llmcmd

统一的 LLM 命令行工具，提供 `llm` 命令来处理对话生成、图片生成/编辑、音频转录和 YAML 批量任务。

## 当前进度

- [x] chat / image / audio / batch 四个子命令
- [x] chat `--edit` diff 文件编辑模式
- [x] image `-n/--count` 多图生成与轻量进度输出
- [x] YAML batch 支持 `edit` 与 `count`
- [x] 发布 GitHub 仓库
- [ ] 发布 PyPI 包

## 安装

```bash
pip install shellus-llmcmd
```

安装后命令名仍为：

```bash
llm
```

## 快速开始

```bash
llm chat "写一段产品介绍"
llm chat "把人物脸型改成偏瘦" --edit prompt.md
llm image "生成三张海报方案" -n 3 -o poster.jpg
llm audio demo.m4a -o demo.srt
llm batch tasks.yaml
```

## 包信息

- PyPI 包名：`shellus-llmcmd`
- CLI 命令名：`llm`
- Python 要求：`>=3.10`

## 文档

详细用法见 [SKILL.md](./SKILL.md)。
