# PyPSA workspace agent instructions

本规范适用于本 workspace 下的 PyPSA 工作。进入具体 checkout 后，先读其
`CONTRIBUTING.md`、配置、Snakefile、规则及更深层 `AGENTS.md`。以当前 checkout
的实际实现为准；PIK、THU、Earth 的目录和配置不可相互套用。
本文件在 workspace 根目录生效；工业仓库中保留相同的可版本化副本。

## 工作边界

- 开始前检查 `pwd`、`git status --short`、分支、worktree 和 remote。识别并保留既有改动。
- 工业开发使用 `PyPSA-China-PIK-industry` 的 `codex/industry-steel-2030`；原
  `PyPSA-China-PIK` 和参考 `PyPSA-China-THU` 保持独立。新任务需要隔离时新建分支/worktree。
- 不自动 reset、清理其他 worktree、改写历史、force push 或向 upstream 推送。
- 修改已有文件在原位完成；临时审计放 `/tmp`。额外持久研究产物放项目的
  `archive/codex_generated/`，不能替代项目应有的代码、数据、配置或测试目录。

## 先仿照现有工作流

PIK 当前布局如下；其他 checkout 先核对自身规则：

| 内容 | 位置 |
| --- | --- |
| 原始/外部输入、审核后的人工转录、来源记录 | `resources/data/<domain>/` |
| 可重建的工作表导出、清洗表、模型输入、中间网络 | `resources/derived_data/`，通过 `PathManager` 获取共享/情景目录 |
| 数据处理和建模代码 | `workflow/scripts/`，按现有 `build_*`、`prepare_*` 等职责组织 |
| Snakemake 依赖和阶段编排 | `workflow/Snakefile` 与 `workflow/rules/*.smk` |
| 默认设置与研究覆盖配置 | `config/`；研究优先用小型 YAML override |
| 单元/集成测试和独立预期样例 | `tests/`、`tests/data/`，样例不能作为正式模型输入 |
| 已求解网络、报告和图表 | `results/` |
| 日志和资源测量 | `logs/`、`benchmarks/` |
| 开发、来源限制和运行说明 | `docs/`；数据域根目录保留一份来源 README |

- 先找同类生产规则，再接入本功能。不要另建顶层 `data/` 或把处理脚本、派生表
  混入原始来源目录，也不要手改生成的 CSV/NetCDF/依赖 manifest。
- 用配置和输入驱动生成过程。规则显式声明原始文件、导入的 helper、映射表、
  参数、输出、日志、线程和内存。嵌套源码快照需要逐文件依赖，不能仅依赖目录时间。
- 关闭新模块时保持既有工作流的目标与依赖。可选数据准备规则不能改变默认目标。
- 配置解析时需要的输入先独立构建，再加载配置覆盖文件，避免 DAG 尚未建立就读取其输出。
- 不硬编码个人绝对路径为生产默认值；复用其他 checkout 的资源需显式指定并只读访问。

## 数据与研究可复现性

- 原始资料按来源和真实发布版本组织，如
  `raw/literature/Lyu et al_2026_Nat.Energy/`、`raw/gem/GEM_2026_09/`。
- 为来源记录 URL/DOI、版本、获取日期、许可、SHA256、单位、地区、参考年份和
  source locator；未知信息写未知。来源发布时间、观测年份和情景年份分别记录。
- 保留完整源码/数据快照和必要原件。冗余 PDF、网页包装及重复压缩包按任务要求
  清理；保留出处、已有摘录和原件校验记录，不删必要计算或空间数据。
- 工业原始下载（含 CSV）和所有生成结果由 Git 忽略；小型来源元数据、审核转录
  与测试样例按当前仓库政策跟踪。提交前用 `git check-ignore` 和暂存区文件清单核实。
- 正常构建不修改来源清单；显式 source-intake 步骤登记新版本和预期导出校验值。
- 缺失不等于零、产能不等于产量。保留原始非数值标记和重复来源行；估计必须有
  `estimate_flag`、方法、输入来源及时间/空间边界。更新测试预期须独立审核数据依据。
- 电力、热、氢、材料和排放边界必须明确，防止电解用电、直接/间接 CO2 重复计入。
  成本需有币种/基年、容量分母和年化依据；不要将净购电当作总过程用电。

## 验证与交付

- 先做受影响的输入/单位/守恒和失败路径检查，再验证实际规则 dry-run 与小规模执行。
  用仓库环境运行相应测试和 `.pre-commit-config.yaml` 检查；不擅自替换 pinned 依赖。
- 数据迁移要核对原件校验、生成结果和所有消费路径；检查配置、测试、文档、
  Git ignore、来源 manifest、下游 implementation/output hashes，不能只移动目录。
- 能源/材料模型修改需相关结构和守恒测试；只在验证需要时运行求解。短时
  smoke/integration case 必须标明时长，不能表述为全年或校准后的科研结论。
- 记录实际完成的检查、失败与限制；不把未运行的步骤写成通过。通过后不无故重复昂贵求解。

## Commit、依赖与 push

- 遵循本仓库 `CONTRIBUTING.md` 的 Conventional Commits（如 `feat`、`fix`、
  `refactor`、`docs`、`test`、`chore`），按可审查的完整功能拆分，附相关测试与文档，
  更新 `CHANGELOG.md` 的 Unreleased。保持人类作者身份，不替换 Git user 配置。
- Codex 参与的每个提交正文末尾添加：

  ```text
  Co-authored-by: Codex <noreply@openai.com>
  ```

- 工业模块维护 `docs/industry/commit_dependencies.md`：写清基础提交、真实前置
  依赖、可 cherry-pick 的组合、外部资源和验证范围；不要为当前提交虚构自己的 hash。
- 暂存明确文件/必要 hunk，检查 `git diff --cached --check`、统计和实际内容；
  不把他人既有改动、下载、临时文件或大型二进制一并加入。
- 用户要求 push 后，检查远端分支状态，正常 push 到用户 fork 的当前开发分支，
  设置 tracking 并核对远端 SHA。保留既有未提交改动；发生分叉先评估，禁止自动 force。
- 若需要 PR，按仓库约定以 `develop` 为通常目标；main 仅遵循仓库 hotfix 流程。
  不自动合并、发布或新建额外 PR，除非任务授权。
- 最后报告权威目录、验证结论、提交与 push 状态，以及仍未完成的必要步骤。

依据：各 checkout 的 `CONTRIBUTING.md`、`.pre-commit-config.yaml`、
`workflow/Snakefile`、`workflow/scripts/_helpers.py::PathManager`，以及工业模块的
`docs/industry/README.md`、`docs/industry/commit_dependencies.md`。
