# Steel-industry input evidence

This directory separates preserved originals (`raw/`, Git ignored), derived
numerical tables (`processed/`), and provenance/transcription (`sources/`). These
are input evidence and explicit demonstration proxies, not a calibrated 2030
steel scenario. No observed data are silently filled with zero.

## Reproduce

Run from the repository root (Python standard library only):

```sh
python3 workflow/scripts/industry_data/build_inputs.py
python3 -m unittest discover -s tests -p test_industry_data.py -v
```

The builder verifies every raw SHA256 before processing. `--download` restores
missing network sources from `sources/manifest.json`. Mutable HTML and Google
exports may no longer match the recorded digest: this intentionally fails closed.
Two Bachorz originals were copied byte-for-byte from the user's existing research
archive; their `local_origin` paths allow restoration on this machine. On another
machine, restore those exact original files from the publication/research archive
and verify the recorded hashes. They have not been represented as freshly
network-downloaded files. No credentials or registration are used.

The original NBS release publishes the table as JPEG. The reviewed transcription
in `sources/nbs_2020_transcription.csv` is the reproducible transcription input,
with original row labels and units. The builder converts 10,000 tonnes to tonnes;
it cannot independently recover text from the image. National/province differences
of 100 tonnes are consistent with displayed rounding.

## Tables and boundaries

| Processed table | Coverage | Interpretation |
| --- | --- | --- |
| `nbs_province_steel_production_2020.csv` | China + 31 provinces, crude steel and pig iron | 2020 production, not capacity. Beijing/Hainan/Tibet blanks retained. |
| `gem_china_plant_capacity_2024.csv` | 743 China plant-status rows | Multiple status rows may share plant ID. Preserve status before aggregating. Not all rows are operating. |
| `gem_china_plant_production_2019_2022.csv` | Plant-year-product records, including missing markers | Only 63 plants have reported 2020 crude steel production, 625.986 Mt; incomplete national coverage. |
| `gem_province_capacity_2026.csv` | 28 provinces × five route categories | September 2026 operating capacity; total 1,088.644 Mt/year. Missing provinces are not proven zero. |
| `henan_sector_electricity_2024.csv` | Eight nested categories in Henan | Industry excludes construction; ferrous includes rolling and ferroalloys, not pure crude steel. |
| `national_sector_electricity_2020.csv` | Five national categories | Secondary industry includes construction; not measured province shares. |
| `route_parameter_candidates.csv` | MPP resources and 2030 cost candidates | Global assumptions, unresolved process/gross/net/currency boundaries. Not model-ready defaults. |
| `bachorz_process_parameter_candidates.csv` | REMIND process coefficients from fixed source archive | Source line provenance, model assumptions; exclude casting/rolling. |

`source_id` joins the manifest; `source_locator` identifies an Excel cell, source
row, or source-code line. Numerical units are explicit, raw nonnumeric markers
are retained where available, and `estimate_flag` distinguishes observed source
values from model assumptions. Source publication years, reference years, hashes,
units and license findings are in the manifest. No raw source is intended for Git.
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

See `sources/gaps.csv` and `sources/literature_evidence.csv`. In particular:

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
  additional approximation. The raw HTML is preserved and hashed.
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
