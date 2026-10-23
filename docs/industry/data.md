# Industry data workflow

Follow the checked-out PIK layout, as used by population, load and power-plant
preparation. `resources/data/industry/` holds original inputs and reviewed source
representations; it contains no processing code or generated workbook exports.
`workflow/scripts/industry_data/` holds Python code, and
`workflow/rules/industry_data.smk` declares the dependencies. `PathManager` selects
the shared derived-data root (`resources/derived_data` normally,
`tests/derived_data` in workflow test mode).

| Location | Contents | Git policy |
| --- | --- | --- |
| `resources/data/industry/raw/` | Versioned original workbooks, complete source/data snapshots, curated CSV source representations | Retained locally, ignored, including raw CSVs |
| `resources/data/industry/sources/` | Source manifest, reviewed NBS transcription, evidence/gap records | Tracked input metadata |
| `resources/derived_data/industry/source_tables/` | All 35 workbook-sheet exports and their generated manifest | Generated, ignored |
| `resources/derived_data/industry/evidence/` | Eight normalized historical/candidate evidence tables | Generated, ignored |
| `resources/derived_data/industry/validation/` | Explicitly estimated 2030 tables, config overlay and dependency hashes | Generated, ignored |
| `tests/data/industry/evidence/` | Reviewed expected CSV snapshots used by portable regression tests | Tracked fixtures; never production inputs |
| `results/`, `logs/`, `benchmarks/` | Model/report outputs, rule logs and resource measurements | Generated, ignored |

## Reproduce

Activate the repository's PyPSA environment and run from its root:

```sh
snakemake -s workflow/Snakefile build_industry_inputs --cores 1
python -m pytest tests/test_industry_data*.py tests/test_industry_resource_paths.py -q
```

The DAG exports worksheets before building evidence. It declares the workbooks,
source manifest, all nested files in source snapshots, curated source CSVs,
province mapping and imported helper modules as dependencies. Both stages verify
registered hashes. Builds do not rewrite source metadata. Input changes must be
registered explicitly, and missing observations are never silently zero-filled.
The source layout is described in the [single source guide](../../resources/data/industry/README.md).

For engineering input generation, copy `config/industry.data.example.yaml` to a
local override, set `industry_data.validation_load` to a complete 2030 provincial
hourly HDF (`/load`), then run:

```sh
snakemake -s workflow/Snakefile build_industry_validation --cores 1 --configfile /path/to/industry-data.yaml
```

The load may be supplied from another checkout as a read-only resource. The rule
is available only when this load path is explicit; ordinary electricity/heat
runs do not acquire an industrial-data requirement. The generated overlay is
`resources/derived_data/industry/validation/config.yaml`. It retains the
`engineering_validation_only` label and is not a calibrated steel scenario.
The reduction-mode direct-CO2 baseline is read during configuration parsing, so
build this bundle before loading its overlay into a model run. This two-step
sequence avoids depending on an output that is needed before the DAG exists.

The Python entry points remain usable without Snakemake:

```sh
python workflow/scripts/industry_data/build_inputs.py --verify-only
python workflow/scripts/industry_data/export_source_tables.py
python workflow/scripts/industry_data/build_inputs.py
python workflow/scripts/industry_data/build_validation_bundle.py --load /path/to/regio_hrly_ac_load_2030.h5
```

The exporter and evidence builder use only the standard library. `--download`
on the evidence builder restores only registered byte-identical direct downloads;
it does not recreate removed PDF/webpage wrappers or extracted repositories.
Restore locally supplied workbooks and snapshots from the recorded release.
Original and repository paths in the schema-3 source manifest are relative to
`resources/data/industry`; worksheet export paths are relative to
`resources/derived_data/industry/source_tables`. These bases are recorded in the
manifest. Historical paths and wrapper hashes are provenance only.

To update a workbook, review its release, source URL, licence, byte count and
SHA256, then update that input record and its export subdirectory. Run
`export_source_tables.py --register` once during this explicit source-intake
step to register expected worksheet hashes. Review the manifest diff and rerun
the workflow. Normal builds never use `--register`. Review affected regression
fixtures independently before replacing them; never refresh expectations merely
to make a failing test pass. Regenerate validation inputs after source, code or
assumption changes so the adapter sees current dependency hashes.

Exports keep every sheet, original Excel column letters and `_source_row`,
including About/Metadata and missing markers. Numeric values and formula results
come from stored XLSX values; formulas are not recalculated. Original workbooks
retain formulas, formatting and links. The NBS input is a reviewed transcription
of the official JPEG with row labels and original units; the builder converts
10,000 tonnes to tonnes, and cannot independently recover text from the image.

## Tables and boundaries

| Processed table | Coverage | Interpretation |
| --- | --- | --- |
| `nbs_province_steel_production_2020.csv` | China + 31 provinces, crude steel and pig iron | 2020 production, not capacity. Beijing/Hainan/Tibet blanks retained. |
| `gem_china_plant_capacity_2026.csv` | 702 China plant-status rows, 458 plants | September 2026 V1; join plant metadata by ID. Multiple status rows may share plant ID. Not all rows are operating. |
| `gem_china_plant_production_2019_2025.csv` | 2,037 source-cell records, 85 plants, including missing markers | September 2026 V1 reports 2020 crude steel production for 35 distinct plants (36 numeric source rows). Repeated plant-year-product records are preserved and flagged; reconcile before aggregating. The 2025 column has no numeric China crude-steel observations. |
| `gem_province_capacity_2026.csv` | 28 provinces × five route categories | September 2026 operating capacity; total 1,088.644 Mt/year. Missing provinces are not proven zero. |
| `henan_sector_electricity_2024.csv` | Eight nested categories in Henan | Industry excludes construction; ferrous includes rolling and ferroalloys, not pure crude steel. |
| `national_sector_electricity_2020.csv` | Five national categories | Secondary industry includes construction; not measured province shares. |
| `route_parameter_candidates.csv` | MPP resources and 2030 cost candidates | Global assumptions, unresolved process/gross/net/currency boundaries. Not model-ready defaults. |
| `bachorz_process_parameter_candidates.csv` | REMIND process coefficients from fixed source archive | Source line provenance, model assumptions; exclude casting/rolling. |

`source_id` joins the manifest; `source_locator` identifies an Excel cell, source
row, or source-code line. Numerical units are explicit, raw nonnumeric markers
are retained where available, and `estimate_flag` distinguishes observed source
values from model assumptions. Source publication years, reference years, hashes,
units and license findings are in the manifest. Raw downloads and generated outputs remain ignored. Source metadata and reviewed
regression fixtures are tracked.
GEM's CC BY 4.0 attribution must be retained. Official statistics lack a verified
explicit open-data license; MPP redistribution license remains unverified.

## Demonstration input generator

`workflow/scripts/industry_data/make_demo_inputs.py` accepts a CSV with
`province,annual_total_mwh`, an explicitly supplied gross steel electricity
intensity, and a missing-data policy. It produces sector `year,province,sector,value,unit`
(`MWh`) and steel-demand `year,province,value,unit` (`t`) tables accepted by the
industry adapter. Its existing-capacity output is **a candidate**, not a complete
adapter input: finite `new_max_tpy`, H2-DRI-EAF rows, resource bounds, route
parameters, direct-emission baseline and costs must be supplied separately.

The generator transfers measured Henan2024 sector shares to every province;
holds NBS2020 output unchanged in2030 and equates production with local demand;
retains GEM2026 capacity in2030; and maps all EAF capacity to scrap-EAF. Every
assumption is labelled. `--missing-policy explicit_zero_scenario` is required to
use zero for source blanks; default is to fail. Unresolved nonsteel ferrous loads
are classified in other industry, not claimed to be observed zero. A steel
baseline exceeding estimated industry electricity raises instead of clipping.
No default gross electricity coefficient is supplied.

## Parameter and scientific gaps

See `resources/data/industry/sources/gaps.csv` and
`resources/data/industry/sources/literature_evidence.csv`. In particular:

- MPP BF-BOF electricity is **negative net purchased electricity**. Never clamp it
  or subtract it from aggregate gross electricity. Coal, coke and byproduct gases
  also cannot all be summed as independent primary inputs.
- Bachorz/REMIND uses near-zero BF electricity as a rough net-power approximation.
  EAF is0.67MWh/t steel; DRI electricity0.08MWh/tDRI; H2 is2.23MWh_LHV/tDRI
  (source conversion0.0333MWh/kg). With1.065tDRI/tsteel, combined H2-DRI-EAF
  candidate electricity is0.7552MWh/tsteel and H2 is2.37495MWh_LHV/tsteel.
  These exclude electrolysis and casting/rolling. Additional EAF carbon and
  auxiliary fuels are omitted in that model simplification, not measured zero.
- Bachorz supplementary S1 gives BF/EAF/DRI capex600/350/420 US dollars per
  stated capacity unit, fixed O&M6%, lifetimes35/20/20 years, utilization0.8.
  Money base year and the DRI capacity denominator require confirmation before
  currency conversion/annualization. S3 fossil-solid factor96tCO2/TJ is a model
  factor, not an observed2020 steel emissions intensity.
- NEU2016 reports a single-plant process electricity sum0.21343MWh per study
  functional tonne (printed external total0.21344). Subtracting hot rolling0.04049
  gives an **estimated**0.17294, still including casting. Source output is1.04266t
  crude steel per functional tonne; using this as per tonne crude steel is an
  additional approximation. The four source tables are retained as CSV; the
  removed HTML's URL and hash remain in the manifest.
- No complete2020 provincial direct-steel CO2 baseline was acquired. CEADs'2020
  inventory is listed behind its user portal; its broader ferrous-combustion
  category also needs process-carbon boundary reconciliation.
- No applicable material inventory maximum was established. Use zero initial
  inventory and zero storage capacity. Fraunhofer's initial/final stock condition
  is not a physical storage upper bound. Unsupported operation flexibility must
  use constant hourly output, not free dispatch.
- National scrap availability, province allocation,2030 demand, finite newbuild
  caps and complete same-boundary route parameters remain explicit scenario or
  additional-data requirements. This evidence alone does not establish a
  science-ready optimization scenario.
