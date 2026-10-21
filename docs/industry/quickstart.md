# Minimal industrial usability check

Run from the industry worktree in the `pypsa-china` environment (tested with
Python 3.12.13, PyPSA 0.35.1, Linopy 0.5.5 and HiGHS 1.14.0). No commercial
solver licence, original national resources or full-year solve is needed for
this test.

```sh
python -m pytest -q -p no:cacheprovider -o log_cli=false \
  tests/test_industry_report_workflow.py::test_snakemake_exports_from_existing_solved_network \
  --basetemp=results/industry_minimal_case
```

This creates and solves a synthetic Anhui system with two three-hour intervals,
then exports the solved NetCDF and runs the actual Snakemake industrial-report
rule against the reimported network. It has fixed electricity demand,
electrolysis, an explicit steel process, active/new capacity, finite feedstocks,
zero inventory and an independently documented removed electricity baseline.
All quantities and costs are synthetic test values. This checks interfaces and
accounting, not empirical steel technology choices.

The test directory below `results/industry_minimal_case/` contains
`results/postnetworks/ntwk_2030.nc` and `results/industry/ntwk_2030/` with:

- `routes.csv`: production, active/new capacity, utilisation, energy/material
  inputs, direct emissions and process costs.
- `inventory.csv`: stock capacity, boundary stocks and stock costs.
- `resources.csv`: physical supply use, finite limits and supply costs.
- `electricity_replacement.csv`: original electricity, baseline removed,
  residual fixed demand, endogenous steel use and gross AC withdrawal.
- `audit.json`: period, physical checks, conventions, provenance and table list.

The test expects 12 tonnes of steel, 6 MWh of direct process electricity, and
21.6 MWh of gross AC withdrawal over six physical hours. It checks zero product
inventory and labels the outputs as a short-period result. Upstream electrolysis
electricity is separate from direct process electricity.

For the complete industrial regression suite, including load decomposition,
adapter modes/EV options, finite capacities, material/CO2 checks, provenance,
corruption rejection and general electricity-report compatibility:

```sh
python -m pytest -q -p no:cacheprovider -o log_cli=false \
  tests/test_industry_loads.py tests/test_industry_model.py \
  tests/test_industry_accounting.py tests/test_industry_adapter.py \
  tests/test_industry_data.py tests/test_industry_reporting.py \
  tests/test_industry_report_export.py tests/test_industry_report_workflow.py
```

For your own PIK run, start with `config/industry.example.yaml` and supply the
documented annual sector and steel inputs. `off` preserves the original Loads;
`fixed_load` disaggregates electricity while retaining fixed steel use;
`endogenous` removes that steel baseline once and attaches the physical process.
EV charging is configured independently. `data/industry/validation/config.yaml`
is an explicitly estimated engineering fixture, not a calibrated scenario.
When endogenous industry is enabled, ordinary `plot_all` includes the industrial
report directory. The same exporter can read an existing solved file directly:

```sh
python workflow/scripts/industry_reporting.py solved.nc output_directory
```

Original downloads remain under ignored `data/industry/raw/`; source manifests,
processing code and normalized data are tracked. Missing source/estimate
declarations appear as unknown, and checksum verification does not establish
empirical calibration. See [the reference comparison](reference_comparison.md)
and [commit dependencies](commit_dependencies.md) before selecting commits.
