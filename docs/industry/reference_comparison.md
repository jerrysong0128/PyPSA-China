# Industrial modelling: THU reference and acceptance criteria

This document records an independent inspection of the THU reference, rather than
claiming replication of its published results. All development belongs in
PyPSA-China-PIK. The adjacent THU checkout is reference material only.

## Reference identity and provenance

| Item | Recorded identity |
|---|---|
| Final article | Lyu et al., *Industrial overcapacity can enable seasonal flexibility in electricity use*, Nature Energy (2026), [doi:10.1038/s41560-026-02073-y](https://www.nature.com/articles/s41560-026-02073-y) |
| Accessible methods | [arXiv:2511.22839v1](https://arxiv.org/html/2511.22839v1), a **preprint**, not the final journal methods or supplement |
| Code | [ruikelyu/PyPSA-China-THU](https://github.com/ruikelyu/PyPSA-China-THU) |
| Inspected source revision | `f353474b43e20686c42094b04441372dadb68b0a` |
| Local reference checkout | Sibling directory `../PyPSA-China-THU` |
| Data record | [Zenodo 19600477](https://zenodo.org/records/19600477), DOI `10.5281/zenodo.19600477`, version 1 |
| Original archive | `data/industry/raw/thu_reference/data.zip` |
| Original record metadata | `data/industry/raw/thu_reference/zenodo-record-19600477.json` |
| Published archive length | `106509944` bytes |
| Published archive MD5 | `f8f102698b1f143ae25083f91e337c98` |
| Data-record licence | **CC-BY-4.0**, verified from `metadata.license.id` in the downloaded Zenodo API response |
| Verification date | 2026-10-21 |

The original ZIP and API JSON must remain unchanged and ignored by Git. Hashes,
source identifiers and this comparison may be committed. See the acquisition
verification section below for actual local checks; published checksum metadata
alone is not evidence that a download completed.

The README declares MIT for code, CC0 for data and CC-BY-4.0 for documentation,
but the inspected tree did not include the named standalone `LICENSES` files.
The specific Zenodo record declares CC-BY-4.0, so do not re-label that archive as
CC0. Retain source attribution and existing SPDX notices in any actual port.
This comparison does not grant permission to redistribute third-party inputs.

## What the paper and code actually cover

The case study is **primary aluminium smelting**, not steel. The final article's
abstract reports savings of CNY 23–32 billion per year. The preprint reports a
different range; its numerical results must not be presented as the final paper's
results. This inspection could read the indexed final abstract and the preprint
methods; it has not verified the complete final journal text or supplement.

The preprint describes provincial smelting capacity, time-dependent production,
finished-product inventories, and electricity-system investment and dispatch.
Its detailed industrial operating problems include startup/shutdown behaviour.
The electricity system is an LP; industrial operating MILPs use its electricity
prices and return revised usage to subsequent electricity-system solves. This
iteration and its convergence criterion are not a proof of global optimality of
the full coupled mixed-integer problem.

The repository README explicitly says that the detailed physical smelter model
and D3R training/reduction code are not all included. It points separately to
DOIs `10.1109/TSG.2026.3736640` and `10.1109/TSG.2025.3545339`, and a
[Data-Driven-Dimension-Reduction repository](https://github.com/Rick10119/Data-Driven-Dimension-Reduction).
Availability of this checkout therefore does not establish complete
reproducibility of those physical modules.

## Code-level comparison

Links below are pinned to the inspected revision.

| Capability | Evidence in THU | Requirement for the PIK steel implementation |
|---|---|---|
| Sector electricity accounting | [prepare_base_network.py](https://github.com/ruikelyu/PyPSA-China-THU/blob/f353474b43e20686c42094b04441372dadb68b0a/scripts/prepare_base_network.py#L222) starts from aggregate provincial electricity, then conditionally removes aluminium demand. [build_load_profiles.py](https://github.com/ruikelyu/PyPSA-China-THU/blob/f353474b43e20686c42094b04441372dadb68b0a/scripts/build_load_profiles.py) builds heat profiles, not a general electricity-sector taxonomy. | Explicit residential, services, industry and other sector inputs with a documented residual policy. Steel is a subset of industry. Validate every province/time-step reconstruction and annual totals. |
| Product-energy conversion | [Links and aluminium buses](https://github.com/ruikelyu/PyPSA-China-THU/blob/f353474b43e20686c42094b04441372dadb68b0a/scripts/prepare_base_network.py#L292) connect electricity to aluminium using 13.3 MWh/t. | Steel routes must declare input/output products, unit conventions, and route-specific electricity, fuels, hydrogen and emissions coefficients. A single aluminium coefficient cannot stand in for steel process modelling. |
| Endogenous electricity replacement | Product demand creates production electricity demand; baseline electricity is deducted before adding the process. | Remove the **documented exogenous steel electricity baseline exactly once**, then let route activity set actual process electricity use. New process electricity need not equal the historical baseline. |
| Capacity | Provincial capacity and capacity scaling are inputs. | Preserve observed provincial/plant capacities and route distinctions where evidence exists; explicit investment/retirement decisions must use costs, lifetimes and bounds rather than silently unlimited production. Missing evidence must not become observed capacity. |
| Product demand | [scenario_utils.py](https://github.com/ruikelyu/PyPSA-China-THU/blob/f353474b43e20686c42094b04441372dadb68b0a/scripts/scenario_utils.py#L254) reads annual demand and distributes it provincially and temporally. | Fixed provincial steel demand as requested; document annual-to-snapshot conversion and time-profile assumptions. No automatic relocation or national market clearing. |
| Inventory | [Store construction](https://github.com/ruikelyu/PyPSA-China-THU/blob/f353474b43e20686c42094b04441372dadb68b0a/scripts/prepare_base_network.py#L311) makes product storage cyclic and extendable, with no finite bound or capital cost at that construction point. | Finite inventory bounds, measured in tonnes, with declared cost and boundary condition. Without evidence, the default is zero inventory; optional nonzero values are labelled assumptions/sensitivities. |
| Product transport | [National hub links](https://github.com/ruikelyu/PyPSA-China-THU/blob/f353474b43e20686c42094b04441372dadb68b0a/scripts/prepare_base_network.py#L353) allow virtually unlimited free bidirectional transfers. | No steel transport links in the fixed-provincial-demand baseline. A later transport option needs explicit capacities, costs and trade accounting. |
| Industrial operation | [solve_network_myopic.py](https://github.com/ruikelyu/PyPSA-China-THU/blob/f353474b43e20686c42094b04441372dadb68b0a/scripts/solve_network_myopic.py#L490) contains representative potline subproblems and iterative dispatch feedback. | Respect the selected **continuous LP** scope. Support evidenced minimum operating levels, availability and ramp constraints where expressible continuously. Do not claim to implement smelter MILPs or discrete steel startup/shutdown. |
| System emissions | [GlobalConstraint](https://github.com/ruikelyu/PyPSA-China-THU/blob/f353474b43e20686c42094b04441372dadb68b0a/scripts/prepare_base_network.py#L215) uses carrier emissions. | Steel fuel and process emissions must enter the actual PIK emissions constraint, with no omitted emissions and no double counting with existing fuel supply. |
| Export and results | [Later iterations](https://github.com/ruikelyu/PyPSA-China-THU/blob/f353474b43e20686c42094b04441372dadb68b0a/scripts/solve_network_myopic.py#L1103) add fixed industrial electricity to Load and remove industrial components; later code backfills components from the first iteration for plotting. | Export the solved model consistently. Re-imported results must retain product, electricity and inventory balances. Tables must distinguish baseline electricity removed from endogenous electricity consumed. |
| Environment | [Environment YAML](https://github.com/ruikelyu/PyPSA-China-THU/blob/f353474b43e20686c42094b04441372dadb68b0a/envs/environment.yaml) pins PyPSA 1.2.2 and Python 3.11, while the README describes an earlier approximately 0.29 environment. | Use and test the PIK environment; do not copy THU solver hooks or environment wholesale. Record tested versions. |

### A specific unit inconsistency to avoid

In the inspected helper, primary demand is converted from ten-thousand tonnes to
tonnes and divided by 8760. The resulting `aluminum_load` is in t/h. At
`prepare_base_network.py:329` (also the alternate path around line 398), the
electricity deduction multiplies this again by `10000 * 13.3 / 8760`.

With the helper's actual units, the consistent conversion is simply
`t/h * MWh/t = MW`. The additional factor `10000 / 8760` is approximately
1.14155. This is a **static dimensional inconsistency in the inspected code**,
not a reproduced diagnosis of the published numerical results. PIK must derive
its own baseline from explicitly labelled annual energy and snapshot weights.

### Aluminium-specific assumptions that must not transfer to steel

- The preprint fixes national primary-aluminium capacity at 45 Mt/year under
  the sector's policy cap, and allocates it using provincial production because
  detailed capacity data were missing and utilisation was near 97%. Provincial
  steel production is not an interchangeable measure of steel capacity.
- Aluminium restart costs, potline sizes, thermal operating rules, electricity
  intensity and material demand scenarios are not steel parameters.
- The preprint's constant provincial capacity shares and aggregated units do
  not establish steel plant survival, retrofit eligibility or route conversion.
- The final paper's seasonal flexibility benefits are a hypothesis to examine
  for steel, not a result supplied by a steel implementation.

## Steel infrastructure acceptance status

Status reviewed on 2026-10-21 against the current source, analytic tests and
saved validation outputs. **Implemented**, **verified in a specified run**, and
**empirically calibrated** are separate claims. The engineering fixtures are
explicitly labelled `engineering_validation_only`; their estimates and missing
observations must not be presented as calibrated provincial steel data.

The accepted baseline is a **continuous LP, fixed provincial steel demand, no
interprovincial material trade, and zero inventory unless an explicit finite
sensitivity is supplied**. These are intentional scope choices. Discrete
startup/shutdown and aluminium potline physics are outside this steel baseline.

### Capability and evidence matrix

Paths below are repository-relative. The test files provide reproducible checks;
the following run records establish the integration scale actually verified.

| Capability | Implementation and verified evidence | Remaining acceptance or research work |
|---|---|---|
| Input provenance | Original downloads are retained under ignored `data/industry/raw/`; processing code and processed/validation tables retain source, unit, year and checksum records. `tests/test_industry_data.py` checks unit conversion, unknown values, and separation of capacity from production. The solved PIK audit checks its input checksums. | Replace explicitly labelled engineering assumptions with sufficient provincial/plant observations. Download retention does not resolve data coverage or redistribution rights. |
| Sector decomposition | `industry_loads.py` and `industry_adapter.py` implement `off`, `fixed_load` and `endogenous` modes. Tests check nonnegative reconstruction, steel within industry, full-year denominators, required provinces and repeat-subtraction rejection. The 31-province 72-hour run reconstructs original electricity with maximum error about `1.46e-11 MW`. | Empirical sector profiles and steel electricity baselines need calibration. Constant annual shares of the provincial hourly shape are an explicit approximation. |
| Endogenous steel electricity | The adapter removes the specified baseline once; `industry_accounting.py` reports original, removed, residual and endogenous electricity separately. Analytic replacement tests and the 72-hour solved audit close the accounting. | Validate a complete national annual replacement table after the annual solve. Endogenous consumption is allowed to differ from the historical baseline. |
| Routes and material balances | `industry_model.py` supplies multiport continuous route Links, fixed provincial product demand and distinct active/new capacity. BF–BOF, scrap-EAF and H2–DRI–EAF are present in the integration fixture. Analytic tests verify material, electricity, fuel and upstream H2 electricity balances. | The 72-hour solve does not prove that every route dispatches. Route coefficients, product boundaries, yields and real plant eligibility require research calibration. |
| Feedstock limits | Finite resource availability, resource prices and input ports are implemented; tests cover binding scrap limits and H2 coupling. Annual resource limits are prorated for a short physical horizon. | Calibrate scrap/ore/fuel supply and costs. A valid finite engineering bound is not evidence of an observed provincial resource budget. |
| Capacity and economics | Installed/new capacity, availability, capacity-basis hours and annual cost conversion are implemented and tested. The seasonal benchmark reconciles capacity, dispatch and inventory costs with the objective. | **Currency/base-year acceptance remains open.** The validation bundle uses `PIK_effective_EUR_unverified_price_year`; existing PIK cost-source conversion/base-year issues remain documented in `scripts/industry_validation/README.md`. Empirical investment/retirement conclusions also need calibrated costs, lifetimes and bounds. |
| Continuous flexibility and stocks | Minimum operating levels, hourly ramps including the cyclic boundary, and finite costed inventory are implemented. Analytic tests show inventory cost changes the decision. The 8760-hour seasonal comparison verifies dispatch shifts with bounded inventory and zero initial/final stock. | Nonzero stock size and steel operating limits need independent evidence or labelled sensitivities. The synthetic 30-day case does not change the zero-inventory default. |
| Provincial boundary | Product demand is served locally with no steel/DRI transfer Links in the baseline. Provincial material balances are checked in analytic tests and solved-network accounting. | No trade or relocation claim is supported or required for this accepted baseline. A future trade extension would need separate accounting and evidence. |
| Emissions | Direct steel emissions enter the joint carbon constraint; upstream electricity remains counted at generation. Analytic tests include a binding cap and route switching. The 72-hour audit reconciles direct steel plus other primary-energy CO2. | The national 72-hour cap is slack, so its result alone is not a carbon-response test. Calibrate process/fuel emission boundaries and validate full-year totals before research interpretation. |
| Chronology and units | Tests cover weighted/coarser snapshots, short-horizon scaling, capacity-basis hours, leap-calendar alignment and rejection of unsupported inputs. The seasonal run uses 8760 consecutive hours with all weights one. National annual networks have been prepared from full-year inputs. | A 72-hour solve is not annual planning. Full 31-province annual optimization and post-solve accounting remain pending; do not turn repeated short windows into a seasonal test. |
| Disabled-mode compatibility | Adapter/load/report tests cover `off`, unchanged unrelated loads and EV option semantics. A full-year disabled-industry PIK network has been prepared. | A full solved baseline regression and all downstream workflow products have not been certified by these checks. |
| PIK integration and persistence | Preparation/solve hooks are connected to the PIK workflow. The 31-province 72-hour HiGHS run is optimal; its solved NetCDF is re-imported by `audit_pik_solution.py`, with carrier balances, carbon accounting and source hashes checked. | Full 31-province 8760-hour solve and complete ordinary workflow/report execution remain outstanding. A prepared annual NetCDF is not a solved annual result. |
| Reporting | `industry_accounting.py` provides route/activity and replacement audits. `plot_statistics.py` and `make_summary.py` exclude tonne-based product Loads from electrical MW totals and include conversion electricity. Reporting tests cover upstream H2, off mode and battery charging. | Full provincial industrial exports covering route output, capacity/investment, fuel/H2, emissions, utilization, inventory, costs and coverage are still being completed. Existing general statistics and energy-balance CSVs do not certify that full report contract. |
| Portable commits | Data processing, load decomposition, process core, adapter, accounting and report compatibility are separated in the development history. `docs/industry/commit_dependencies.md` records the intended dependency order. | Finalize the dependency ledger against the current rewritten history and verify cherry-picks onto the intended formal-work base. Paths here avoid stale implementation hashes. |

Electrical reporting uses **gross AC withdrawal**: fixed AC Loads plus positive
AC consumption by conversion Links, including industrial production, electrolysis
and battery charging. It excludes product tonnes and AC-to-AC transmission, but
is not final electricity consumption or a net measure after battery discharge.
See [electricity reporting definitions](electricity_reporting.md).

### Test verification boundary

The analytic coverage referenced above is in `tests/test_industry_model.py`,
`tests/test_industry_accounting.py`, `tests/test_industry_loads.py`,
`tests/test_industry_adapter.py`, `tests/test_industry_data.py` and
`tests/test_industry_reporting.py`. Earlier successful checks and the persisted
solve/audit records establish the evidence described here. An independent
combined rerun on 2026-10-21 was **incomplete** because filesystem writes failed
with `ENOSPC` (`No space left on device`; approximately 119 MiB available).
It is not a fresh whole-suite pass and does not supersede those earlier records.
No additional repeat was attempted after identifying the storage limitation.

### Verified runs and their limits

**Single-province seasonal benchmark.**
[`run_seasonal_benchmark.py`](../../scripts/industry_validation/run_seasonal_benchmark.py)
and [the benchmark record](seasonal_benchmark.md) describe two optimal HiGHS
solves with 8760 consecutive physical hours, synthetic Anhui and a synthetic
EAF route. The saved
`results/industry_seasonal_benchmark/summary.json` and hourly/monthly CSVs show:

- Both cases produce 87,600 t and use 70,080 MWh of direct steel electricity.
- The finite-inventory sensitivity builds 7,200 t of inventory capacity; both
  pre-first-hour and final stocks are zero. Its low-price-quartile production
  rises from 21,910 t to 26,776.745 t, while high-price-quartile production falls
  from 21,910 t to 14,710 t.
- Synthetic objective cost falls by 5.2322%, after including production-capacity
  and inventory costs. The largest objective-reconciliation error is below
  `8e-7` synthetic currency units and material residual below `3e-10 t`.
- Joint CO2 remains 31,755 t in both cases; the 35,000 t cap is slack. This is
  evidence of working seasonal-shifting machinery, **not an empirical steel
  saving or emissions benefit**, and not a national annual simulation.

**31-province PIK integration, 72 hours.**
`results/industry_validation/endogenous_72h/solved_2030.nc`, `validation.json`,
`solution_audit.json`, `solver.log` and `highs-run.log` record the April 1–3, 2030
run under PyPSA 0.35.1 / HiGHS 1.14.0. HiGHS reports **optimal**. Physical,
objective, generator and store weights each sum to 72 hours. The re-import audit
checks eight source-file hashes, Load reconstruction, material balances and the
joint carbon account. Maximum provincial steel material residual is about
`2.21e-8 t`. Total CO2 is 31,902,937.48 t over this engineering test period,
comprising 13,395,602.90 t direct steel and 18,507,334.58 t other primary-energy
emissions. These are fixture outputs, **not calibrated national emissions**.
The audit explicitly sets `annual_result: false`.

**National annual preparation, not yet annual optimization.**
`results/industry_validation/off_annual_prepare/` records full-year disabled-mode
preparation and calendar checks. The endogenous annual directory contains
`prepared_2030.nc` and configuration/resource audits, but no verified solved
annual network at this review. Annual preparation uses the original full-year
inputs and annual cost scaling; it is not obtained by extending the solved
72-hour network. The next national acceptance gate is an optimal 31-province
8760-hour solution followed by physical, financial and reporting audits.

The current continuous LP therefore has implemented and partially integrated
industrial infrastructure spanning the reference's production, capacity,
inventory, electricity and emissions concerns. Its technical validation is now
beyond a small LP alone. Full national annual validation, complete reporting and
empirical calibration remain separate unfinished gates. Neither the synthetic
seasonal comparison nor the national short-horizon run reproduces the paper's
aluminium results or establishes steel seasonal benefits in China.

## Acquisition verification

Completed on 2026-10-21:

- Full Git clone succeeded at `../PyPSA-China-THU`; origin is
  `https://github.com/ruikelyu/PyPSA-China-THU.git`.
- Actual `HEAD` equals `f353474b43e20686c42094b04441372dadb68b0a`; checkout is
  detached at that revision and its working tree is clean. The commit's recorded
  date is `2026-10-14T21:42:42-04:00`.
- Local archive length is **106509944 bytes**, equal to the published length.
- Computed local MD5 is **`f8f102698b1f143ae25083f91e337c98`**, equal to the
  Zenodo API checksum.
- Computed local SHA-256 is
  **`18a4b3861a5efd0cf2e4be619b28a6af8317b9fea7d971731a2aff12c87adf3f`**.
- Python `zipfile.ZipFile.testzip()` returned `None`: CRC verification passed for
  all **572 members**, including directory and macOS metadata entries. No
  extraction or reformatting of the source archive was performed.
- Downloaded API JSON SHA-256 is
  `95047050af13125f2430cab74bea9bddd5d54e2afa91e295ae3ee80e9fbb9644`.
- Machine-readable checks and the complete member inventory are retained as
  `data/industry/raw/thu_reference/local-verification.json` and
  `data/industry/raw/thu_reference/archive-members.json`.
- `git check-ignore` confirms that the downloaded ZIP is ignored by
  `/data/industry/raw/**`.

The archive contains aluminium demand JSON and provincial capacity/demand/share
CSVs, technology costs, existing infrastructure, load/weather inputs and other
power-system inputs. It is reference data, **not** a source of calibrated steel
route coefficients. The member inventory preserves original paths, lengths and
CRC values without treating `__MACOSX` metadata as scientific tables.

To recheck locally without changing the original files:

```sh
git -C ../PyPSA-China-THU rev-parse HEAD
git -C ../PyPSA-China-THU status --short
shasum -a 256 data/industry/raw/thu_reference/data.zip
python -m zipfile -t data/industry/raw/thu_reference/data.zip
git check-ignore -v data/industry/raw/thu_reference/data.zip
```
