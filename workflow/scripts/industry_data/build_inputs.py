"""Rebuild steel evidence tables from preserved raw sources (Python stdlib only).

Run from the repository: python workflow/scripts/industry_data/build_inputs.py
CSV exports preserve unknown/N/A markers, original sheet rows, and status;
capacity is never substituted for production. Source paths come from the manifest.
"""

import argparse
import csv
import hashlib
import json
import re
import urllib.request
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

from export_source_tables import sheet_rows
from industry_paths import DATA, EVIDENCE, ROOT, SOURCE_TABLES


def number(value, factor=1):
    """Convert finite source numbers while retaining missing values as blanks."""
    try:
        val = Decimal(value)
        return str(val * factor) if val.is_finite() else ""
    except (InvalidOperation, TypeError):
        return ""


def province_mapping():
    """Load the existing PIK province-name mapping."""
    with (ROOT / "resources/data/regions/province_codes.csv").open() as f:
        return {r["Full name"]: r["Code"] for r in csv.DictReader(f)}


def normalize_province(value):
    """Normalize source province aliases without inventing missing regions."""
    return {"Inner Mongolia": "InnerMongolia", "Shaanxi province": "Shaanxi"}.get(value, value)


class EvidenceBuilder:
    """Read registered sources and write generated evidence to an explicit directory."""

    def __init__(self, data=DATA, source_tables=SOURCE_TABLES, output=EVIDENCE):
        self.data = Path(data)
        self.source_tables = Path(source_tables)
        self.output = Path(output)
        self.manifest = json.loads((self.data / "sources/manifest.json").read_text())

    def source_record(self, source_id):
        """Return registered metadata for a source identifier."""
        manifest = self.manifest
        return next(s for s in manifest["sources"] if s["source_id"] == source_id)

    def source_path(self, source_id):
        """Resolve the original input path from its registered metadata."""
        return self.data / self.source_record(source_id)["original_path"]

    def source_sheet(self, source_id, sheet):
        """Read a registered workbook export with original cell coordinates."""
        return sheet_rows(
            self.source_tables / self.source_record(source_id)["csv_export_directory"], sheet
        )

    def named_sheet(self, source_id, sheet, required):
        """Yield source rows keyed by the selected header row."""
        rows = iter(self.source_sheet(source_id, sheet))
        _, header = next(rows)
        columns = {name: col for col, name in header.items() if name}
        missing = set(required) - columns.keys()
        if missing:
            raise ValueError(f"{source_id}/{sheet}: missing columns {sorted(missing)}")
        for rownum, row in rows:
            yield rownum, {name: row.get(col, "") for name, col in columns.items()}

    def write_csv(self, name, rows, fields=None):
        """Write generated rows with stable field order and CSV encoding."""
        rows = list(rows)
        fields = fields or list(rows[0])
        with (self.output / name).open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def process_gem(self):
        """Normalize GEM capacities and production with status and source markers."""
        codes = province_mapping()
        source = "gem_2026_plants"
        plants = {}
        for rownum, row in self.named_sheet(
            source, "Plant data", ["GEM plant ID", "Country/area", "Subnational unit"]
        ):
            if row["Country/area"] == "China":
                if row["GEM plant ID"] in plants:
                    raise ValueError("Duplicate plant metadata: " + row["GEM plant ID"])
                plants[row["GEM plant ID"]] = (rownum, row)
        rows = []
        for rownum, r in self.named_sheet(
            source,
            "Plant capacities and status",
            ["GEM plant ID", "Country/area", "Status", "Nominal crude steel capacity (ttpa)"],
        ):
            if r["Country/area"] != "China":
                continue
            metadata_row, plant = plants[r["GEM plant ID"]]
            province = normalize_province(plant["Subnational unit"])
            if province not in codes:
                raise ValueError("Unmapped China plant province: " + province)
            record = dict(
                plant_id=r["GEM plant ID"],
                plant_name=plant["Plant name (English)"],
                province=province,
                province_code=codes[province],
                status=r["Status"],
                start_year_raw=r["Start date"],
                coordinates=plant["Coordinates"],
                route_raw=r["Main production equipment"],
                source_id=source,
                source_locator=f"Plant capacities and status!{rownum}",
                metadata_locator=f"Plant data!{metadata_row}",
                reference_year=2026,
                source_row_id=f"gem2026-{rownum}",
                wiki_url=plant["GEM wiki page"],
            )
            for col, label in [
                ("Nominal crude steel capacity (ttpa)", "crude_steel"),
                ("Nominal BOF steel capacity (ttpa)", "bof"),
                ("Nominal EAF steel capacity (ttpa)", "eaf"),
                ("Nominal BF capacity (ttpa)", "bf"),
                ("Nominal DRI capacity (ttpa)", "dri"),
                ("Nominal IF steel capacity (ttpa)", "if"),
                ("Other/unspecified steel capacity (ttpa)", "other_steel"),
            ]:
                record[label + "_capacity_tpy"] = number(r[col], 1000)
                record[label + "_capacity_raw"] = r[col]
            rows.append(record)
        self.write_csv("gem_china_plant_capacity_2026.csv", rows)
        production = []
        _, headers = next(iter(self.source_sheet(source, "Plant production")))
        for rownum, r in self.named_sheet(
            source, "Plant production", ["GEM plant ID", "Type of production", "2019.0", "2025.0"]
        ):
            if r["GEM plant ID"] not in plants:
                continue
            _, plant = plants[r["GEM plant ID"]]
            province = normalize_province(plant["Subnational unit"])
            variable = r["Type of production"].removesuffix(" (ttpa)").lower().replace(" ", "_")
            if not r["Type of production"].endswith(" (ttpa)"):
                raise ValueError("Unexpected production unit: " + r["Type of production"])
            # The CSV retains original year headers, including Excel numeric suffixes.
            for col, header in headers.items():
                match = re.fullmatch(r"(\d{4})(?:\.0)?", header)
                if not match:
                    continue
                production.append(
                    dict(
                        plant_id=r["GEM plant ID"],
                        province=province,
                        province_code=codes[province],
                        year=int(match[1]),
                        variable=variable,
                        value=number(r[header], 1000),
                        unit="t/year",
                        raw_value=r[header],
                        estimate_flag=False,
                        source_id=source,
                        source_locator=f"Plant production!{col}{rownum}",
                    )
                )
        counts = Counter((r["plant_id"], r["year"], r["variable"]) for r in production)
        for record in production:
            record["repeated_plant_year_product"] = (
                counts[record["plant_id"], record["year"], record["variable"]] > 1
            )
        self.write_csv("gem_china_plant_production_2019_2025.csv", production)
        rows = []
        for rownum, r in self.source_sheet(
            "gem_2026_province_capacity", "MethodChinaCapacitySteel"
        ):
            province = normalize_province(r.get("A", ""))
            if province not in codes:
                continue
            for col, route in [
                ("B", "total"),
                ("C", "BOF"),
                ("D", "EAF"),
                ("E", "IF"),
                ("F", "other"),
            ]:
                rows.append(
                    dict(
                        province=province,
                        province_code=codes[province],
                        year=2026,
                        route=route,
                        value=number(r.get(col, ""), Decimal("1000.0")),
                        unit="t/year",
                        variable="operating_capacity",
                        estimate_flag=False,
                        source_id="gem_2026_province_capacity",
                        source_locator=f"MethodChinaCapacitySteel!{col}{rownum}",
                    )
                )
        self.write_csv("gem_province_capacity_2026.csv", rows)

    def process_nbs(self):
        """Normalize reviewed provincial crude-steel production transcriptions."""
        rows = []
        with self.source_path("nbs_2021_table13_13").open() as f:
            for r in csv.DictReader(f):
                for var in ["pig_iron", "crude_steel"]:
                    raw = r[var + "_10000t"]
                    rows.append(
                        dict(
                            province=r["province"],
                            province_code=r["province_code"],
                            year=2020,
                            variable=var + "_production",
                            value=number(raw, 10000),
                            unit="t/year",
                            raw_value=raw,
                            source_id="nbs_2021_table13_13",
                            source_locator="C13-13.jpg:" + r["source_row"],
                            estimate_flag=False,
                            method="manual_image_transcription_visual_review",
                            missing_reason="" if raw else "blank_in_source_not_assumed_zero",
                        )
                    )
        self.write_csv("nbs_province_steel_production_2020.csv", rows)

    def process_henan(self):
        """Normalize the reviewed Henan electricity source representation."""
        labels = {
            "全社会用电总计": "total",
            "第一产业": "primary",
            "第二产业": "secondary",
            "第三产业": "tertiary",
            "城乡居民生活用电合计": "residential",
            "工业": "industry",
            "制造业": "manufacturing",
            "黑色金属冶炼和压延加工业": "ferrous_smelting_rolling",
        }
        rows = []
        with self.source_path("nea_henan_2024").open(encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                label = row["sector_label"]
                if label in labels:
                    rows.append(
                        dict(
                            province="Henan",
                            province_code="HA",
                            year=2024,
                            sector=labels[label],
                            value=number(row["annual_value"], 100000),
                            unit="MWh/year",
                            raw_value=row["annual_value"],
                            raw_unit="亿千瓦时",
                            source_id="nea_henan_2024",
                            source_locator="annual cumulative:" + label,
                            estimate_flag=False,
                            boundary_note="ferrous includes rolling and ferroalloys; not identical to crude steel"
                            if labels[label] == "ferrous_smelting_rolling"
                            else "published electricity consumption",
                        )
                    )
        assert len(rows) == 8, f"Unexpected Henan source structure: {len(rows)} rows"
        self.write_csv("henan_sector_electricity_2024.csv", rows)

    def process_technology(self):
        """Collect candidate process parameters from preserved literature inputs."""
        rows = []
        routes = {"Avg BF-BOF": "BF-BOF", "EAF": "scrap-EAF", "DRI-EAF_100% green H2": "H2-DRI-EAF"}
        with self.source_path("mpp_business_cases").open(encoding="utf-8-sig") as f:
            for line, r in enumerate(csv.DictReader(f), 2):
                for source_route, route in routes.items():
                    value = r[source_route]
                    unit = r["Unit"]
                    if unit == "GJ/t steel":
                        value = str(Decimal(value) / Decimal("3.6"))
                        unit = "MWh/t steel"
                    rows.append(
                        dict(
                            route=route,
                            parameter=r["Material"],
                            value=value,
                            unit=unit,
                            source_id="mpp_business_cases",
                            source_locator=f"row {line}; column {source_route}",
                            source_year="2022 model; fixed commit 9eca52d",
                            estimate_flag=True,
                            readiness="candidate_requires_boundary_review",
                            note="BF electricity is net purchased (negative export); coal/coke/byproduct gases must not be summed as independent primary inputs. H2 LHV basis and electricity boundary require review.",
                        )
                    )
        for sheet in ["GF capex", "Renewal capex", "Other Opex"]:
            for num, r in self.source_sheet("mpp_capex_opex", sheet):
                if r.get("A") in routes:
                    rows.append(
                        dict(
                            route=routes[r["A"]],
                            parameter=sheet,
                            value=r.get("L"),
                            unit="source cost unit requires confirmation",
                            source_id="mpp_capex_opex",
                            source_locator=f"{sheet}!L{num}",
                            source_year="2030 column; 2020 money per PyPSA technology-data",
                            estimate_flag=True,
                            readiness="candidate_requires_currency_and_boundary_review",
                            note="Do not treat Other Opex as FOM before checking fixed/variable coverage; annuity and currency conversion not applied.",
                        )
                    )
        self.write_csv("route_parameter_candidates.csv", rows)

    def process_bachorz(self):
        """Extract REMIND assumptions with line provenance; no automatic model inputs."""
        path = self.source_path("bachorz_remind_code")
        name = str(path.relative_to(self.data / "raw"))
        lines = path.read_text().splitlines()
        selected = [
            ("H2-DRI", "pellets_t_per_tdri", 'p37_specMatDem("dripell","idr","h2")', "t/tDRI"),
            ("DRI-EAF", "dri_t_per_tsteel", 'p37_specMatDem("driron","eaf","pri")', "tDRI/tsteel"),
            (
                "scrap-EAF",
                "scrap_t_per_tsteel",
                'p37_specMatDem("eafscrap","eaf","sec")',
                "t/tsteel",
            ),
            ("BF", "ore_t_per_tpigiron", 'p37_specMatDem("ironore","bf","standard")', "t/tpigiron"),
            (
                "BOF",
                "pigiron_t_per_tsteel",
                'p37_specMatDem("pigiron","bof","unheated")',
                "tpigiron/tsteel",
            ),
            (
                "H2-DRI",
                "hydrogen_lhv_mwh_per_tdri",
                'p37_specFeDemTarget("feh2s","idr","h2")',
                "MWh_LHV/tDRI",
            ),
            (
                "H2-DRI",
                "electricity_mwh_per_tdri",
                'p37_specFeDemTarget("feels","idr","h2")',
                "MWh/tDRI",
            ),
            (
                "DRI-EAF",
                "electricity_mwh_per_tsteel",
                'p37_specFeDemTarget("feels","eaf","pri")',
                "MWh/tsteel",
            ),
            (
                "scrap-EAF",
                "electricity_mwh_per_tsteel",
                'p37_specFeDemTarget("feels","eaf","sec")',
                "MWh/tsteel",
            ),
            (
                "BF",
                "coal_mwh_per_tpigiron",
                'p37_specFeDemTarget("fesos","bf","standard")',
                "MWh/tpigiron",
            ),
        ]
        rows = []
        for route, parameter, key, unit in selected:
            hits = [(i + 1, line) for i, line in enumerate(lines) if line.startswith(key)]
            if len(hits) != 1:
                raise ValueError("REMIND source structure changed: " + key)
            num, line = hits[0]
            value = re.search(r"=\s*([0-9.]+)", line)[1]
            rows.append(
                dict(
                    route=route,
                    parameter=parameter,
                    value=value,
                    unit=unit,
                    source_id="bachorz_remind_code",
                    source_locator=f"{name}:{num}",
                    estimate_flag=True,
                    readiness="candidate_model_assumption_not_observation",
                    boundary_note="EAF excludes casting/rolling; H2 excludes electrolysis; BF electricity uses near-zero net power approximation. Source TODO flags integrated-plant boundary; do not use as gross electricity set.",
                )
            )
        self.write_csv("bachorz_process_parameter_candidates.csv", rows)

    def process_national_electricity(self):
        """Normalize national electricity evidence without provincial extrapolation."""
        rows = []
        with self.source_path("nea_national_2020").open(encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                if row["raw_unit"] != "亿千瓦时":
                    raise ValueError("Unexpected national electricity unit")
                rows.append(
                    dict(
                        province="China",
                        province_code="CN",
                        year=2020,
                        sector=row["sector"],
                        value=number(row["annual_value"], 100000),
                        unit="MWh/year",
                        source_id="nea_national_2020",
                        source_locator="annual electricity paragraph",
                        estimate_flag=False,
                        boundary_note="secondary includes construction; national share is not measured provincial share",
                    )
                )
        self.write_csv("national_sector_electricity_2020.csv", rows)

    def build(self):
        """Verify all dependencies before constructing normalized evidence tables."""
        verify_raw(self.data)
        verify_exports(self.data, self.source_tables)
        self.output.mkdir(parents=True, exist_ok=True)
        self.process_gem()
        self.process_nbs()
        self.process_henan()
        self.process_technology()
        self.process_national_electricity()
        self.process_bachorz()


def verify_raw(data=None):
    """Verify immutable source files and full source-directory fingerprints."""
    data = Path(data) if data is not None else DATA
    manifest = json.loads((data / "sources/manifest.json").read_text())
    for source in manifest["sources"]:
        files = list(source.get("additional_files", []))
        if source.get("original_path"):
            files.append(dict(path=source["original_path"], sha256=source["sha256"]))
        for entry in files:
            p = data / entry["path"]
            if hashlib.sha256(p.read_bytes()).hexdigest() != entry["sha256"]:
                raise ValueError(
                    f"Checksum mismatch for {p}; do not silently process changed source"
                )
        if source.get("repository_directory"):
            directory = data / source["repository_directory"]
            digest = hashlib.sha256()
            count = 0
            for p in sorted(directory.rglob("*")):
                if not p.is_file() or p.name == ".DS_Store":
                    continue
                checksum = hashlib.sha256(p.read_bytes()).hexdigest()
                digest.update((str(p.relative_to(directory)) + "\0" + checksum + "\n").encode())
                count += 1
            expected = source["directory_fingerprint"]
            if count != expected["files"] or digest.hexdigest() != expected["sha256"]:
                raise ValueError("Source directory changed: " + str(directory))


def verify_exports(data=DATA, source_tables=SOURCE_TABLES):
    """Reject changed or missing worksheet exports before processing."""
    manifest = json.loads((Path(data) / "sources/manifest.json").read_text())
    for source in manifest["sources"]:
        for entry in source.get("csv_exports", []):
            path = Path(source_tables) / entry["path"]
            if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
                raise ValueError(f"Checksum mismatch for {path}; rebuild worksheet exports")


def download(data=None):
    """Restore registered byte-identical downloads; source intake stays explicit."""
    data = Path(data) if data is not None else DATA
    manifest = json.loads((data / "sources/manifest.json").read_text())
    for source in manifest["sources"]:
        if not source.get("original_path"):
            continue
        path = data / source["original_path"]
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            if not source.get("download_url"):
                raise FileNotFoundError(
                    f"Restore registered source {path}; its upstream URL is provenance, not a byte-identical replacement"
                )
            request = urllib.request.Request(
                source["download_url"], headers={"User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(request) as response:
                body = response.read()
            if hashlib.sha256(body).hexdigest() != source["sha256"]:
                raise ValueError("Downloaded source changed: " + source["source_id"])
            path.write_bytes(body)
    verify_raw(data)


def main():
    """Build evidence through either Snakemake or the explicit CLI."""
    if "snakemake" in globals():
        context = globals()["snakemake"]
        from contextlib import redirect_stderr, redirect_stdout

        log = Path(context.log[0])
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("w") as stream, redirect_stdout(stream), redirect_stderr(stream):
            EvidenceBuilder(
                Path(context.input.manifest).parent.parent,
                context.input.tables,
                Path(context.output[0]).parent,
            ).build()
            print("Verified registered sources and generated eight evidence tables.")
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true")
    parser.add_argument(
        "--verify-only", action="store_true", help="Verify sources without writing generated data"
    )
    parser.add_argument("--data", type=Path, default=DATA)
    parser.add_argument("--source-tables", type=Path, default=SOURCE_TABLES)
    parser.add_argument("--output", type=Path, default=EVIDENCE)
    args = parser.parse_args()
    if args.download:
        download(args.data)
    if args.verify_only:
        verify_raw(args.data)
    else:
        EvidenceBuilder(args.data, args.source_tables, args.output).build()


if __name__ == "__main__":
    main()
