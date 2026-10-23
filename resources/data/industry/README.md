# 工业数据来源与目录

按本项目现有 `resources/data` 约定整理，更新日期：2026-10-23。
本层只保留这一份说明；来源仓库原有的 README、许可证和配置文件保留。

```text
resources/data/industry/
├── README.md
├── sources/                         来源清单、证据缺口与审核后的 NBS 转录
└── raw/                             原始文件，全部由 Git 忽略
    ├── gem/
    │   ├── GEM_2026_09/             五份原始 XLSX，钢铁 V1、所有权 V2
    │   └── GEM_2025_12/             一份原始煤/铁矿石产消 XLSX
    ├── literature/
    │   ├── Lyu et al_2026_Nat.Energy/data/
    │   ├── Bachorz et al_2026_Nat.Clim.Change/remind/
    │   ├── MPP_2022_steel-model/    原始技术参数 CSV 和成本 XLSX
    │   └── Li et al_2016_J.Northeastern.Univ/table*.csv
    └── statistics/
        ├── NEA_2024_Henan/          原网页提取的用电/发电 CSV
        └── NEA_2020_China/          全国分产业用电 CSV
```

| 来源 | 保留内容与边界 |
| --- | --- |
| GEM 2026-09 | 原始钢铁省级产能、工厂、钢设备、铁设备、所有权工作簿。产量列覆盖 2019–2025；不能把发布日期当成产量年份。 |
| GEM 2025-12 | 此煤/铁矿石文件本身是 2025 版，保留真实版本。 |
| Lyu et al., Nature Energy | Zenodo 数据包的 251 个模型与数据文件；按最终论文/数据包年份将旧目录 2025 改为 2026。它是数据包，代码仓库在 workspace 的 `PyPSA-China-THU`。 |
| Bachorz et al., Nature Climate Change | REMIND 固定版本 `051c3ec4d9b7d7cc97086a1822d28b948435a48c` 的完整 962 文件源码快照，保留内部结构和许可证。 |
| MPP | 原始技术 CSV 与成本 XLSX；仍是需审核系统边界、成本单位和基年的候选参数。 |
| Li et al., 2016 | 四张科学数据表 CSV，HTML 合并单元格已展开；单厂数据不能直接当成全国均值。 |
| NEA / NBS | 原网页数据表/段落的 CSV 与审核后的 NBS 图像转录；缺失值保持缺失。 |

独立 PDF、HTML/HTM、网页脚本、重复 ZIP 和 macOS 杂项已移除。
Lyu 数据包只额外省去一个地理说明 PDF，数值及空间文件完整保留。
来源 URL、版本、许可记录、原件/历史包装文件 SHA256 和完整目录指纹集中在
`sources/manifest.json`，已摘录的证据和局限在 `sources/literature_evidence.csv`、
`sources/gaps.csv`。工作簿原件保留原字节、公式、格式及链接。

所有生成数据均位于 `resources/derived_data/industry/`：

- `source_tables/`：35 个工作表 CSV，保留 sheet 名、Excel 列字母、`_source_row`、
  `N/A` 和 `>0`；采用文件中存储的数值/公式缓存，不重新计算。
- `evidence/`：八份标准化历史/候选证据表。GEM 2026 产能包含 702 个工厂状态行、
  458 家工厂；重复产量行保留 `repeated_plant_year_product` 标记，汇总前需核对。
- `validation/`：明确标记为工程验证的 2030 输入、配置覆盖文件和依赖校验记录。

处理代码在 `workflow/scripts/industry_data/`，规则在
`workflow/rules/industry_data.smk`。从仓库根目录运行：

```sh
snakemake -s workflow/Snakefile build_industry_inputs --cores 1
python workflow/scripts/industry_data/build_inputs.py --verify-only
```

完整重建、数据更新、验证输入生成和测试说明见
[工业数据工作流](../../../docs/industry/data.md)。正常构建不会修改来源清单；新增版本
应先登记原件和来源，显式更新预期 CSV 校验值，再重建下游结果。
原始下载和所有生成数据保持 Git 忽略；本说明及来源元数据进入版本控制。
