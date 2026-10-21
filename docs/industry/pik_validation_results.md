# PIK integration validation, 2026-10-21

These are engineering integration checks using the explicitly estimated inputs in
`data/industry/validation/`. They are not calibrated scientific steel scenarios.
Original PIK files were read only. Generated networks, solver logs, configurations,
and numerical audits remain gitignored under `results/industry_validation/`.

## Current acceptance: minimal case

The user explicitly selected minimal usability testing on 2026-10-21. A fresh
combined run of all eight industrial test modules passed: **101 tests in 23.83 s**.
The separately invoked [quick-start test](quickstart.md) also passed in 5.81 s.
It solves two three-hour intervals with HiGHS, saves/reimports the NetCDF and
executes the actual Snakemake industrial-report rule. CSV readback confirms
12 t steel, 6 MWh direct steel electricity, 21.6 MWh gross AC withdrawal and zero
product inventory; `annual_result` is false. These are synthetic analytic values.

The durable example output is below
`results/industry_minimal_case/test_snakemake_exports_from_ex0/`, including
`results/postnetworks/ntwk_2030.nc` and `results/industry/ntwk_2030/`. The test
runner owns that directory and recreates it when the quick-start command is run.
No full-year solve is required for the current acceptance.

## Environment and reproducibility

The interpreter was `/Users/jerrysong/anaconda3/envs/pypsa-china/bin/python`:
Python 3.12.13, PyPSA 0.35.1, Linopy 0.5.5, NumPy 1.26.4, pandas 2.2.3,
HiGHS/highspy 1.14.0, and Gurobi/gurobipy 12.0.3 on Apple M4 Pro.
The original run configuration is
`../PyPSA-China-PIK/results/v-1.3.2_20261020_hourly_3days/overnight_co2pw-exp175default_topo-current+FCG/run_config.yaml`.

The runner and complete commands/override structure are described in
[`scripts/industry_validation/README.md`](../../scripts/industry_validation/README.md).
The independent validation carbon scenario is `industry_validation_reduction`,
with `control: reduction` and a 2030 reduction of `0.41175086`. The configuration
handler adds the estimated 2020 direct steel baseline to the original power/heat
baseline before converting the reduction to a carbon budget. Electricity-only
budgets were not reused unchanged for the expanded scope. Every run used physical
hourly weights of one, no load shedding, and no `nhours` reweighting.

## Successful 31-province, 72-hour endogenous check

The source is the original **unsolved brownfield** `ntwk_2030.nc`, April 1–3,
2030. Its 31 provincial electricity loads match exactly the corresponding slice
of the complete 8760-hour HDF. The industry adapter normalizes sector shares on
that full-year HDF before selecting the 72-hour solve window.

Default Gurobi license discovery selected a restricted license and rejected the
model size. A separate HiGHS override then solved the same model to **optimal**:

| Check | Observed value |
|---|---:|
| Rows / columns / nonzeros | 294,903 / 129,269 / 663,033 |
| Solver time | 49.32 s |
| HiGHS IPM iterations / crossover iterations | 71 / 25,250 |
| Objective, PIK effective monetary basis | 3,174,888,290.5536 |
| Primal-dual objective error reported by HiGHS | 3.75e-15 |
| Physical hours; each snapshot weighting sum | 72 |
| AC cumulative balance residual | −1.00e-5 MWh |
| Steel product cumulative balance residual | 0 t |
| Largest steel-accounting residual across reported checks | 2.21e-8 |
| Inventory residual | 0 |
| Removed fixed steel electricity baseline | 1,986,616.9401 MWh |
| Endogenous direct steel electricity | 1,513,485.6419 MWh |
| Total scoped direct CO2 | 31,902,937.4809 t |
| Direct steel CO2 | 13,395,602.8969 t |
| Period carbon limit | 32,259,883.1812 t |
| VRE curtailment fraction | 3.4398% |
| AC marginal price minimum / median / maximum | 0.005 / 21.2358 / 180.8809 |

HiGHS options were IPM, crossover on, 4 threads, primal/dual feasibility tolerance
1e-7, and IPM optimality tolerance 1e-8. The scalar maximum accounting residual
mixes named checks with different units; inspect `solution_audit.json` for each
check and do not interpret it as one physical error metric.

The solved network was exported, reimported, and independently rechecked with
`industry_accounting.validate_industry_solution`. All recorded input checksums
match the current input files. Outputs are `endogenous_72h/solved_2030.nc`,
`validation.json`, `solution_audit.json`, `statistics.csv`, `energy_balance.csv`,
`highs-run.log`, and `solver.log`. The Gurobi license-size failure is also recorded
in `gurobi_failure.json`.

```sh
python scripts/industry_validation/audit_pik_solution.py \
  results/industry_validation/endogenous_72h/solved_2030.nc \
  --output-dir results/industry_validation/endogenous_72h
```

The electricity change is an accounting check, not an estimated energy-saving
benefit. Upstream hydrogen electricity is excluded from the direct-process field
and included in gross AC withdrawal. The short window and estimated route inputs
do not establish annual route choices, costs, emission reductions, or reliability.

During the final handover, the new exporter read the existing solved NetCDF and
wrote `endogenous_72h/industry_reports/` without rerunning optimization. Readback
checks 138 route/vintage rows, 31 inventory rows, 84 resource rows and 31 electricity
replacement rows. Total production is 8,751,507.1233 t, direct process electricity
1,513,485.6419 MWh and direct steel CO2 13,395,602.8969 t; the largest provincial
baseline reconstruction error is below 1e-9 MWh. This older saved network predates
embedded input-quality metadata, so its report correctly labels quality as
`unknown` / `not_provided`. A present-day manifest is not silently assigned to an
older solution; separate retained input-hash evidence remains available.

## Successful annual preparation; resource-limited annual solve

The runner rebuilt the independent 2030 electricity network using original full
annual electricity/heat profiles, weather-derived VRE/COP/solar-thermal inputs,
2030 technology costs, and existing capacity data. Brownfield additions used the
normal PIK functions. Capital costs were rebuilt using `n_years=1`; a short-window
network was not extended or reweighted.

Original VRE profiles have a 2020 calendar with February 29 omitted. The normal
PIK mapping preserves month/day/hour and maps to the 2030 nonleap calendar. The
result has **8760 consecutive hours**, all weights equal one, zero missing VRE
availability values, and provincial loads exactly matching the full HDF. The
calendar check is in `off_annual_prepare/calendar_check.json`; complete greenfield,
brownfield, prepared networks, cost table, resource inventory, and configurations
are retained in that directory.

The full endogenous network was then prepared from this annual brownfield network
with the same engineering steel bundle and a 2020 nuclear-capacity reference. An
explicit `GRB_LICENSE_FILE=/Library/gurobi1301/gurobi.lic` selected the full local
Gurobi license; no license contents were read or copied. The resulting annual LP
was accepted by Gurobi and had:

| Check | Observed value |
|---|---:|
| Rows | 35,681,127 |
| Columns | 15,593,909 |
| Nonzeros | 80,404,448 |
| LP file writing time | 108.63 s |
| Gurobi presolve time before termination | 2.72 s |
| Gurobi soft memory limit | 12 GB |
| Termination | Memory limit reached |

Gurobi options were `Threads=4`, `Method=2`, `Crossover=0`, `BarConvTol=1e-7`,
`FeasibilityTol=1e-6`, and `SoftMemLimit=12`. Process RSS was sampled at about
9.12 GiB during LP construction and 2.10 GiB after writing; these samples are not
a peak-memory measurement. Gurobi's soft limit applies to its allocations, not to
all Python/Linopy allocations. Gurobi also warned about large RHS/bounds: matrix
range 2e-3–8e4, objective range 5e-3–4e6, RHS up to 3e10, and finite bounds 2e10.
Those warnings did not establish infeasibility; the observed stop was memory.

**No annual feasible or optimal solution was produced.** The solver wrapper
correctly rejected non-optimal termination. The prepared annual network and logs
are available in `endogenous_annual/`; no `solved_2030.nc` is claimed. The model
retained full hourly chronology and was not simplified to bypass the limit.
A future annual solve requires enough memory or equivalent model/solver memory
improvements, followed by a new post-export accounting audit.

After disk space became available, a separate retry was prepared under
`endogenous_annual_retry/` with `Threads=2` and `SoftMemLimit=24` GB. The user then
requested minimum-case usability testing instead of a full-year solve. That retry
was interrupted during Linopy LP-file construction, before Gurobi optimization,
and exited with code 130; its process was independently confirmed absent. This
is a user-requested stop, not a solver failure. Prepared inputs, exact bundle
snapshot/checksums, preflight logs, and `run_status.json` remain in that directory.
No further annual retry is required for the current acceptance scope.

The actual annual command was:

```sh
GRB_LICENSE_FILE=/Library/gurobi1301/gurobi.lic \
MPLCONFIGDIR=/private/tmp/pypsa-steel-mpl \
python -u scripts/industry_validation/run_pik_validation.py \
  --source-root ../PyPSA-China-PIK \
  --config \
    ../PyPSA-China-PIK/results/v-1.3.2_20261020_hourly_3days/overnight_co2pw-exp175default_topo-current+FCG/run_config.yaml \
    data/industry/validation/config.yaml \
    results/industry_validation/endogenous_annual/override.yaml \
  --network results/industry_validation/off_annual_prepare/brownfield_2030.nc \
  --nuclear-baseline-network ../PyPSA-China-PIK/results/v-1.3.2_20261020_hourly_3days/overnight_co2pw-exp175default_topo-current+FCG/prenetworks-brownfield/ntwk_2020.nc \
  --annual-load ../PyPSA-China-PIK/resources/derived_data/overnight_co2pw-exp175default_topo-current+FCG/load/regio_hrly_ac_load_2030.h5 \
  --co2-pathway industry_validation_reduction \
  --output-dir results/industry_validation/endogenous_annual --solve
```

The PIK monetary price year remains unverified: source cost units mix EUR without
a stated year, one explicit EUR-2020 entry, and USD rows, while the inherited cost
loader applies the USD conversion twice. This validation preserves that behavior
and labels the steel bundle's currency basis accordingly; it does not certify
scientifically comparable levelized costs.
