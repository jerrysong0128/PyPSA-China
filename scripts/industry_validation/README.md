# PIK network integration validation

Run from the industry worktree with the `pypsa-china` environment. The runner reads
original PIK resources and only writes below this worktree's `results/`. Default
execution builds/prepares a network; add `--solve` to optimize. It does not invent
steel coefficients. The bundle in `data/industry/validation` is an explicitly
estimated engineering fixture, not a calibrated scientific scenario.

## Existing 31-province, 72-hour network

```sh
python scripts/industry_validation/run_pik_validation.py \
  --source-root ../PyPSA-China-PIK \
  --config \
    ../PyPSA-China-PIK/results/v-1.3.2_20261020_hourly_3days/overnight_co2pw-exp175default_topo-current+FCG/run_config.yaml \
    data/industry/validation/config.yaml \
    results/industry_validation/endogenous_72h/override.yaml \
  --network ../PyPSA-China-PIK/results/v-1.3.2_20261020_hourly_3days/overnight_co2pw-exp175default_topo-current+FCG/prenetworks-brownfield/ntwk_2030.nc \
  --annual-load ../PyPSA-China-PIK/resources/derived_data/overnight_co2pw-exp175default_topo-current+FCG/load/regio_hrly_ac_load_2030.h5 \
  --co2-pathway industry_validation_reduction \
  --output-dir results/industry_validation/endogenous_72h \
  --solve
```

The separate override used for this engineering check is:

```yaml
co2_scenarios:
  industry_validation_reduction:
    control: reduction
    pathway:
      2030: 0.41175086
solving:
  gurobi_hpc_tunnel:
    use_tunnel: false
  options:
    load_shedding: false
  solver:
    name: highs
    options: industry-validation-highs
  solver_options:
    industry-validation-highs:
      solver: ipm
      run_crossover: "on"
      threads: 4
      primal_feasibility_tolerance: 1.0e-7
      dual_feasibility_tolerance: 1.0e-7
      ipm_optimality_tolerance: 1.0e-8
```

The existing 2030 source network covers April 1–3 (72 consecutive hours), 31 AC
and 31 H2 buses. All three snapshot weight columns sum to 72. Its electricity
loads exactly equal the same slice of the 8760×31 annual HDF. Use the unsolved
brownfield network: solved output or already-prepared global constraints are
rejected. The example uses installed HiGHS. Default Gurobi license discovery selected a
restricted license. Setting `GRB_LICENSE_FILE=/Library/gurobi1301/gurobi.lic`
explicitly selects the available full license (verified by a local LP solve).
A selected commercial solver must be licensed locally; no remote HPC
license tunnel is established by this runner.

The original run config has **period** CO2 budgets (2030: 25,571,855.754352 t
for 72 hours). When using that budget directly, explicitly pass
`--budget-input-hours 72`. For an annual budget pass `--budget-input-hours 8760`.
Reduction/price configurations require no budget-hours flag. The runner writes
`annual_config.yaml`, `solve_config.yaml`, `prepared_2030.nc`, and `validation.json`;
a successful solve additionally writes `solved_2030.nc` and `solver.log`.
The root solver's steel audit runs on endogenous configurations.

## Annual construction from original resources

Replace `--network ...` with `--build-annual` and add:

```sh
--nuclear-baseline-network ../PyPSA-China-PIK/results/v-1.3.2_20261020_hourly_3days/overnight_co2pw-exp175default_topo-current+FCG/prenetworks-brownfield/ntwk_2020.nc
```

Use a separate output directory, e.g. `results/industry_validation/endogenous_annual`.
`--check-resources` checks named construction inputs without building. The runner
calls the same PIK preparation, cost-loading, existing VRE and brownfield capacity
functions as the normal overnight workflow. Full-year energy costs are rebuilt
with `n_years=1`; extending the 72-hour network by repeating or reweighting its
snapshots would retain incorrect period-scaled capital costs and is unsupported.
The annual builder currently supports independent (non-REMIND), nonleap planning.

Reusable files are inventoried in `resource_audit.json`: full annual electricity
and heat HDF; regional heating fractions; COP and solar-thermal profiles; 2030
technology costs; province shapes; biomass potential; installed capacities; and
onshore/offshore wind and solar profile NetCDFs. Configuration resource paths are
resolved against `--source-root`. Scenario-level cached inputs are located
alongside the explicitly supplied annual electricity file.

The weather profiles use 2020 with February 29 omitted (a 25-hour timestamp gap).
PIK's normal calendar mapping retains month/day/hour and replaces the year with
2030. The resulting solve calendar must have exactly consecutive hourly snapshots
and weights of one; the runner checks this rather than relaxing chronology.
Weather/calendar mapping provenance is retained in network metadata.

## Limits and interpretation

The cost loader targets EUR, but a single common price year cannot currently be
verified. The source CSV contains predominantly EUR units without a price year,
one explicit EUR 2020 unit, and five USD rows. The original loader applies its
USD conversion twice. This runner preserves existing behavior and does not claim
the cost inputs are consistently EUR2013. The engineering bundle labels its
monetary basis `PIK_effective_EUR_unverified_price_year` accordingly.

Short-window success establishes that network interfaces, balances, constraints,
and solver integration work. It does not establish annual steel-route choices,
realistic costs, annual reliability, or calibrated national emissions.


## Audit a solved network

```sh
python scripts/industry_validation/audit_pik_solution.py \
  results/industry_validation/endogenous_72h/solved_2030.nc \
  --output-dir results/industry_validation/endogenous_72h
```

This exports component statistics, carrier balances, AC price distribution,
VRE curtailment, CO2 constraints, a fresh steel accounting audit recomputed after importing the solved network, and input
checksum comparisons. A mismatch reports source drift; it does not silently
relabel an older solution as using newer inputs.

For full-year Gurobi validation, the machine-specific license environment can be
set explicitly with `GRB_LICENSE_FILE=/Library/gurobi1301/gurobi.lic`; the runner
never reads or copies license contents. Use a separate solver-options set with
`Threads: 4`, `Method: 2`, `Crossover: 0`, `BarConvTol: 1.0e-7`,
`FeasibilityTol: 1.0e-6`, and `SoftMemLimit: 12` (GB). This limits Gurobi's memory,
not Python/Linopy's model-construction allocations. Watch both process memory and
`run.log`/`solver.log`; do not replace chronological hours with representative
weights to evade a resource limit.
