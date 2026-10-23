# Commit dependencies and cherry-pick bundles

Development branch: `codex/industry-steel-2030` in `PyPSA-China-PIK-industry`.
Verified PIK base: `3ba042b201470e1f8b74e4356247565b4f8aee0d`.
The original `PyPSA-China-PIK` checkout and its local modifications are separate.
Every development commit includes `Co-authored-by: Codex <noreply@openai.com>`.

The table distinguishes import/patch prerequisites from correctness companions.
For normal use select a bundle below: an earlier uncorrected implementation is
not the supported final model merely because it imports. Prerequisites are
transitive. Raw downloads and generated results do not travel with a cherry-pick.

## Functional ledger

| Commit | Cohesive function | Prerequisites and important boundaries |
|---|---|---|
| `75501c4` | Development/data policy and raw-data Git exclusion | Base only; include with all bundles. |
| `34dbca3` | Standalone provincial sector-load split and conservation tests | No steel-model dependency. |
| `0f4f73d` | Continuous steel process/capacity/resource core and cyclic operation | Base only; use with the following bounded-inventory fix. |
| `5429e08` | Optimize finite inventory and validate external buses | `0f4f73d`; required correctness companion for nonzero stock. The inventory cost argument already existed before this fix. |
| `27bc0a7` | Joint carbon accounting, electrical reserves and solve callback | `0f4f73d`; use after `5429e08`. Includes the `_helpers.py` CO2-pathway handling. |
| `4bec6d5` | Workflow adapter, off/fixed/endogenous modes and baseline replacement | `34dbca3` + `0f4f73d`; endogenous use also takes `5429e08` and `27bc0a7`. The adapter imports the steel module even for fixed/off modes. |
| `af5942b` | Source provenance, original-download policy and normalized steel evidence | Independent of the industrial model; raw files must be acquired separately. |
| `4c654dd` | Keep material units out of general electrical reports | `27bc0a7` and its core prerequisites; general report scripts import `industry_accounting` unconditionally. |
| `1703fe6` | Define gross AC withdrawal including battery charging | `4c654dd`. |
| `8f85789` | Audit original, removed and endogenous electricity separately | `27bc0a7`; replacement auditing also needs metadata produced by `4bec6d5`. |
| `aee956a` | Reproducible, explicitly estimated 2030 engineering input bundle | `af5942b` + `0f4f73d`; use with corrected model core. Not a calibrated scenario. |
| `58cfa4f` | Original-PIK preparation/solve runner and persisted-network audits | `4bec6d5` + `27bc0a7`; use `8f85789` + `41a7f49` for current complete audits. Example bundle commands also need `aee956a` and original PIK resources. |
| `7b9a316` | Pinned THU reference and capability comparison | Documentation only; no runtime prerequisite. The final documentation revision updates its acceptance status. |
| `41a7f49` | Persisted zero-output handling and finite solved-bound validation | `5429e08` + `27bc0a7`; apply after `8f85789` because of patch context. Use the later reporting-fixture fix with general report tests. |
| `a22b79b` | Audited industrial CSVs/JSON and standalone saved-network exporter | `41a7f49` supplies the required `solved_output` API. |
| `52aae43` | Verify inputs before mutation and persist source/estimate coverage | `4bec6d5` + `aee956a`; take after `41a7f49`, whose model bytes the fixture manifest records. A changed formal-work model requires explicit bundle regeneration. |
| `b08398b` | Conditional Snakemake industrial reports and `plot_all` dependency | `4bec6d5` + `a22b79b`. |
| `69c34b5` | Carry embedded input provenance into report JSON and CSV labels | `a22b79b`; `52aae43` is the optional metadata producer. Missing historical metadata stays unknown. |
| `8d78b9d` | Give the hand-calculated reporting fixture its matching zero objective | `4c654dd`; required test companion to `41a7f49` in the reporting bundle. Does not change model behavior. |
| `5d41cca` | Optional synthetic seasonal benchmark and existing-run record | Corrected core (`5429e08`) + accounting (`27bc0a7`); use the core/audit bundle below. Not needed for minimal usability. |
| `2fc144b` | PIK resource layout, immutable source exports, GEM September 2026 evidence and workspace development policy | Parent `d0e20ef` and its transitive prerequisites; carry scripts, rules, metadata, fixtures and consumer paths together. Raw sources remain local. |

The earlier handover documentation commit only updates instructions, validation
records and this ledger; it adds no runtime dependency and deliberately does not
embed its own commit hash.

## Selectable bundles

Run these commands from the target repository **after making the source commits
available there**. Fetch `origin/codex/industry-steel-2030` first. Start from the named
PIK base or assess changes in the formal-work base first. Do not reset an existing
working branch to follow these examples.

Standalone load-splitting functions:

```sh
git cherry-pick 75501c4 34dbca3
```

Data processing/provenance only, without industrial network modules:

```sh
git cherry-pick 75501c4 af5942b
```

Fixed sector Loads through the workflow (the adapter also imports the core):

```sh
git cherry-pick 75501c4 34dbca3 0f4f73d 4bec6d5
```

Corrected physical steel core and complete solution audits, without workflow:

```sh
git cherry-pick 75501c4 0f4f73d 5429e08 27bc0a7 8f85789 41a7f49
```

Endogenous workflow, corrected physical/accounting core and all reports:

```sh
git cherry-pick 75501c4 34dbca3 0f4f73d 5429e08 27bc0a7 4bec6d5 \
  4c654dd 1703fe6 8f85789 41a7f49 a22b79b b08398b 69c34b5 8d78b9d
```

After that bundle, add the current engineering input tables and verified row
provenance as a separate choice:

```sh
git cherry-pick af5942b aee956a 52aae43
```

After the core/audit bundle, `5d41cca` adds only the optional seasonal technical
benchmark. After the endogenous bundle plus engineering inputs, `58cfa4f` adds
the original-PIK integration runner. Neither is necessary for the six-hour
[usability check](quickstart.md).

## Verification boundary

The 2026-10-23 source-layout/GEM refresh is a cohesive migration on top of
`d0e20efb53eb244dcff92fb9549d1006f2dc0ab1` (including its transitive model,
workflow and validation prerequisites), recorded in `2fc144b`. Use the current
development branch for this pipeline. To select only this migration on its exact
parent, apply `git cherry-pick 2fc144b` from a branch already containing
`d0e20ef`; the historical minimal data-only bundle is not sufficient.
The historical standalone data bundle
above retains its historical layout; it is not the current pipeline.

Carry the migration's scripts, `industry_paths.py`, Snakemake include/rules,
schema-3 source manifest, configuration paths, regression fixtures and consumer
path fix together. Evidence production uses the standard library; the optional
validation builder uses the existing PyPSA environment and `industry_model`.
No environment-package dependency was added. These migrations have not been
certified as an independent cherry-pick onto a later formal-work revision.

Raw downloads remain local under `resources/data/industry/raw`; generated exports,
evidence and engineering inputs remain ignored under
`resources/derived_data/industry`. Restore raw inputs using the
[source guide](../../resources/data/industry/README.md), then run the rules in
[data.md](data.md). Normal builds verify registered checksums without rewriting
the source manifest. Regenerate the validation bundle after any source or
implementation change. Its estimates remain engineering checks, not calibrated
research results. Historical bundle audits below concern their stated commits.

Current migration checks: **107 industrial tests passed from an exported index
snapshot**, without ignored raw downloads or unrelated local changes. The real
three-rule Snakemake pipeline rebuilt 35 worksheet exports, eight evidence tables
and nine validation files. All eight evidence files matched the reviewed
fixtures; seven numerical/route validation files were byte-identical to the
pre-migration outputs. All source/implementation/output hashes verified, and a
subsequent dry-run required no jobs. The configured pre-commit hooks passed.
These checks do not constitute an annual scientific optimization.

The parent worktree passed all **101 industrial tests** on 2026-10-21. Each of the
six bundles above was also applied by actual cherry-picks into detached temporary
worktrees from the exact PIK base, with **no patch conflicts**. The last bundle
was checked by appending the data/provenance suffix after the complete report
chain, rather than relying only on the branch's original chronological order.

| Isolated bundle | Additional nonsolving checks |
|---|---|
| Standalone loads | Imports/AST and 21 load tests passed. |
| Data only | Imports/AST and 7 tests passed; the same 7 also passed with standard-library `unittest`. |
| Core plus audits | Imports/AST and 3 selected structural/input checks passed. |
| Fixed-load workflow | Imports/AST and all 21 adapter tests available in that selected history passed. |
| Endogenous workflow and all reports | Imports/AST and 4 analytic general-report tests passed. |
| Endogenous/report bundle plus input/provenance suffix | Imports, 21-file AST check, 8 output/4 implementation hashes and 38 nonsolving tests passed. |

During subset tests, optimization was replaced by a guard that raises on any
solve attempt. The temporary worktrees were removed after checking; logs were
retained under `/private/tmp/industry-cherrypick-audit/20261021T202552/` on the
validation machine. This certifies these selected patches against the stated
base, not compatibility with later independently modified formal-work revisions.

The original checkout's `_pypsa_helpers.py` and `plot_time_series.py` local edits
are not part of these commits. This development does not silently depend on them.
Keep generated networks/results and ignored raw sources separate from portable
processing code and normalized inputs.
