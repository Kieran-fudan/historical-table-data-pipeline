# 历史表格数据流水线

[English](README.md)

一个可审计、由 profile 驱动的工具链：将**扫描型历史记录表**的多份独立 OCR 结果核对为研究数据。

> **适用边界：** v0.1 只包含完全虚构的合成示例，不宣称在任何真实语料、真实文献家族或出版物上完成验证，也不承诺 100% 识别准确。

工具保留每个 OCR 来源的原文和候选值，显式生成待审项、应用机器可读的决定，并在发布前校验来源链。多源一致只是证据，不等于原文真值。

## 为什么做这个仓库

历史表格数字化通常把 OCR、临时脚本、Excel 手改和没有记录的人工判断混在一起。本项目把它们拆成可以复查的状态转换：

核心思路是核对足够独立的转录来源：不一致项进入审查；在明确的统计假设下，一致项可以降低“多个来源独立出错却未被发现”的概率。相关性错误会削弱甚至消除这一收益，所以仍需对原图进行抽样复核；详见[方法中的统计直觉](docs/methodology.md#statistical-intuition-not-a-guarantee)。

`candidate（候选） -> decision（决定） -> apply（应用） -> validate（校验）`

仓库提供：

- Python 包和统一的 `historical-table` CLI；
- 可接收不同 OCR 引擎的规范 JSONL 契约；
- profile 驱动的解析、对齐、标准化和质量检查；
- 显式审查文件，不做无记录的静默修正；
- 稳定的记录/单元格 ID 与来源溯源；
- 面向研究使用的记录表、长表价格和质量摘要；
- 可供 Codex、Claude Code 和其他 Agent Skills 宿主共用的 Skill。

真实 PDF、页面图片、OCR 文本和提取后的真实数据**默认不公开**。仓库只放自制的合成示例。

## 当前状态与证据边界

这是 alpha 阶段的研究工具。`profiles/example-records.yaml` 和 `examples/synthetic/` 下的全部文件均为有意构造的虚构材料，只用于测试软件契约与审查闭环，不构成真实 OCR 准确率或任何真实文献家族适用性的证据。适配真实材料时，需要新建或修订 profile、抽查代表性页面、对原图进行审计并记录验证方法。

## 安装

需要 Python 3.11 或更高版本。

```bash
python -m venv .venv
```

Windows PowerShell 中激活环境：

```powershell
.\.venv\Scripts\Activate.ps1
```

macOS/Linux 中激活环境：

```bash
source .venv/bin/activate
```

从当前仓库安装核心包：

```bash
python -m pip install --upgrade pip
python -m pip install .
```

按需安装可选能力：

```bash
# 开发测试、lint 和构建工具
python -m pip install ".[dev]"

# 本地 PDF 渲染
python -m pip install ".[pdf]"

# 可选的 OpenAI-compatible 联网 OCR 适配器
python -m pip install ".[ocr]"

# PDF、OCR 和研究分析依赖
python -m pip install ".[all]"
```

这里有意采用普通安装。部分 Windows/Python 组合在仓库路径含非 ASCII 字符时，无法正确解析 editable 安装生成的 `.pth` 文件。修改包源码后请重新执行安装命令。

离线核对多份 OCR 的核心流程不需要 API key。

## 合成示例快速开始

运行内置的无网络演示：

```bash
historical-table demo --output runs/demo
```

demo 会核对仓库内的合成 OCR，把审查 ledger 编译为规范的单元格决策，完成校验，并发布合成记录。

如需检查每一个阶段，可以显式运行同一套 fixture：

```bash
historical-table profile-validate profiles/example-records.yaml

historical-table reconcile \
  --profile profiles/example-records.yaml \
  --input examples/synthetic/ocr/engine-a.jsonl \
  --input examples/synthetic/ocr/engine-b.jsonl \
  --output runs/synthetic
```

`reconcile` 会追加一个由内容派生的 run ID。复制输出中的 `run_directory`，替换下方的 `RUN_DIR_FROM_RECONCILE`：

```bash
historical-table review-export RUN_DIR_FROM_RECONCILE \
  --output runs/synthetic-review

historical-table review-apply RUN_DIR_FROM_RECONCILE \
  --decisions examples/synthetic/decisions/reconciliation.jsonl \
  --profile profiles/example-records.yaml \
  --output runs/synthetic-applications \
  --default-reviewer synthetic-fixture \
  --default-decided-at 2000-01-01T00:00:00Z
```

`review-apply` 也会追加内容派生的 application ID。复制其输出中的 `application_directory`，替换 `APPLICATION_DIR_FROM_REVIEW_APPLY`：

```bash
historical-table validate APPLICATION_DIR_FROM_REVIEW_APPLY \
  --profile profiles/example-records.yaml \
  --report runs/synthetic-validation.json

historical-table publish APPLICATION_DIR_FROM_REVIEW_APPLY \
  --profile profiles/example-records.yaml \
  --output runs/synthetic-publication
```

`review-export` 输出规范的单元格级决策模板。仓库内的 ledger 为便于阅读采用高层工作流事件；CLI 会先把这些事件编译为同一个单元格契约，再执行应用。校验和发布默认阻止未决单元格；只有在明确且已记录要发布不确定值时，才使用 `--allow-unresolved`。

请以当前安装版本各子命令的 `--help` 为准。合成 manifest 和预期产物位于 [`examples/synthetic`](examples/synthetic/)。

## 流程

| 阶段 | CLI 命令 | 是否联网 | 主要产物 |
| --- | --- | --- | --- |
| 检查配置 | `profile-validate` | 否 | 通过结构校验的 profile |
| 渲染选定页面 | `render` | 否 | 本地页面图片 |
| 可选托管 OCR | `ocr --allow-network` | 是 | 规范 OCR JSONL |
| 核对多个来源 | `reconcile` | 否 | 一致/冲突候选项 |
| 准备审查 | `review-export` | 否 | 候选包和决定模板 |
| 应用决定 | `review-apply` | 否 | 已编译决策和已审查共识 |
| 检查契约 | `validate` | 否 | 校验与质量结果 |
| 生成研究产物 | `publish` | 否 | 记录、长表价格、质量摘要 |

离线模式下，可以使用任意 OCR 引擎，再将结果转换成规范 JSONL。`ocr` 命令只是可选入口，目前提供 OpenAI-compatible 适配器，而且没有显式 `--allow-network` 时不会联网。

## Profile 与数据模型

- 新的记录型表格从 [`profiles/template.yaml`](profiles/template.yaml) 开始。
- 适配新材料前先读 [profile 指南](docs/profile-guide.md)。
- 生成 JSONL 前先读 [数据模型](docs/data-model.md)。
- 原始值与标准化值必须分开保存。
- 价格采用长表，不按币种不断增加成对宽列。
- PDF 物理页、印刷页码、表格 ID 和源行号分别保存。

profile 通过结构校验，不代表另一本出版物的版式已经得到支持。

## 可选 Agent Skill

[`skills/digitize-historical-tables`](skills/digitize-historical-tables/) 是模型中立的 Agent Skill。它只调用同一个 `historical-table` CLI，并强制遵循“候选 → 决定 → 应用 → 校验”。

- Codex 项目级使用：把整个 Skill 目录复制到 `.agents/skills/` 下。
- Claude Code 项目级使用：复制到 `.claude/skills/` 下。
- 其他 Agent Skills 宿主按各自发现规则加载同一个 `SKILL.md`。

工作流不包含宿主专属工具或本机路径。`agents/openai.yaml` 只提供可选的 OpenAI 界面元数据，不改变通用指令。宿主的发现与安装方式可参考 [OpenAI 官方 Skill 文档](https://learn.chatgpt.com/docs/build-skills)和 [Claude Code Skill 文档](https://code.claude.com/docs/en/slash-commands)。

## 仓库结构

```text
src/historical_table_pipeline/   Python 包
profiles/                        profile 模板与虚构示例 profile
examples/synthetic/              可再分发的合成端到端样例
tests/                           单元和集成检查
skills/digitize-historical-tables/  可选 Agent Skill
docs/                            架构、方法、模型、限制和指南
```

## 文档

- [架构](docs/architecture.md)
- [方法](docs/methodology.md)
- [数据模型](docs/data-model.md)
- [Profile 指南](docs/profile-guide.md)
- [限制](docs/limitations.md)
- [公开发布检查表](docs/publication-checklist.md)
- [安全政策](SECURITY.md)
- [贡献指南](CONTRIBUTING.md)

## 数据、权利与隐私

Apache-2.0 只覆盖本仓库的软件和原创文档，不授予复制或公开原出版物、扫描件、OCR 文本及用户派生数据的权利。处理或公开材料前，需要分别审查著作权、数据库权益、访问条件、隐私和 OCR 服务条款。

不要提交 `.env`、API key、真实文档、本地 agent 设置、运行目录、日志或备份。若使用托管 OCR，应记录页面发送到哪里，并事先取得必要授权。

## 引用与许可

请使用 [`CITATION.cff`](CITATION.cff)，并引用实际使用的 release 或 commit、profile 版本、输入标识与哈希、OCR 来源和审查政策。软件采用 [Apache-2.0](LICENSE)；补充署名和数据许可边界见 [`NOTICE`](NOTICE)。
