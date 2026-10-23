"""Produce explicitly estimated 2030 province inputs; never substitutes for data.

Requires a provincial annual-electricity CSV (province, annual_total_mwh), plus
user-specified scenario assumptions. Reuses measured Henan2024 sector shares in
all provinces as a transparent proxy. Steel tonnes are 2020 NBS production held
constant, NOT local final consumption or a 2030 forecast. Blank NBS rows require
an explicit policy argument; no silent zero fill. Does not create route energy,
emissions, costs, or resource caps where the evidence is incomplete.
"""

import argparse
import csv
import math
from pathlib import Path

from industry_paths import DERIVED, EVIDENCE


def generate(totals, gross_electricity, missing_policy, evidence=EVIDENCE):
    """Build labeled provincial engineering proxies from explicit evidence inputs."""
    if not math.isfinite(gross_electricity) or gross_electricity <= 0:
        raise ValueError("Explicit gross steel electricity must be positive")
    if not totals:
        raise ValueError("At least one province is required")
    if missing_policy not in ("fail", "explicit_zero_scenario"):
        raise ValueError("Unknown missing policy")
    evidence = Path(evidence)
    with (evidence / "henan_sector_electricity_2024.csv").open() as f:
        henan = {r["sector"]: float(r["value"]) for r in csv.DictReader(f)}
    shares = {
        "agriculture": henan["primary"] / henan["total"],
        "industry": henan["industry"] / henan["total"],
        "construction": (henan["secondary"] - henan["industry"]) / henan["total"],
        "services": henan["tertiary"] / henan["total"],
        "residential": henan["residential"] / henan["total"],
    }
    with (evidence / "nbs_province_steel_production_2020.csv").open() as f:
        production = {
            r["province"]: r
            for r in csv.DictReader(f)
            if r["variable"] == "crude_steel_production" and r["province"] != "China"
        }
    sector_rows = []
    demand = []
    capacity = []
    with (evidence / "gem_province_capacity_2026.csv").open() as f:
        caps = {(r["province"], r["route"]): float(r["value"]) for r in csv.DictReader(f)}
    for province, total in totals.items():
        if province not in production or not math.isfinite(total) or total <= 0:
            raise ValueError("Unknown province or nonpositive total: " + province)
        prod = production[province]
        missing = not prod["value"]
        if missing and missing_policy != "explicit_zero_scenario":
            raise ValueError("NBS blank requires explicit policy for " + province)
        tonnes = float(prod["value"]) if prod["value"] else 0.0
        steel_mwh = tonnes * gross_electricity
        industry = total * shares["industry"]
        if steel_mwh > industry:
            raise ValueError(
                f"{province}: estimated steel electricity exceeds proxy industry; revise assumptions, never clip"
            )
        # The separate ferrous residual is unobserved. Keep it in other_industry
        # as an explicit classification scenario, not a statement of zero use.
        for sector, value in dict(
            **{k: total * v for k, v in shares.items()}, steel=steel_mwh, other_ferrous=0.0
        ).items():
            method = "Henan2024 share transferred unchanged to 2030 province"
            sources = "nea_henan_2024"
            if sector == "steel":
                method = f"2020 crude steel held constant x explicit assumed gross electricity {gross_electricity}MWh/t"
                sources = "nbs_2021_table13_13;explicit_cli_assumption"
            elif sector == "other_ferrous":
                method = "unresolved ferrous residual classified in other_industry; zero explicit category only"
                sources = "explicit_classification_scenario"
            sector_rows.append(
                dict(
                    province=province,
                    year=2030,
                    sector=sector,
                    value=value,
                    unit="MWh",
                    estimate_flag=True,
                    source_id=sources,
                    method=method,
                )
            )
        demand.append(
            dict(
                province=province,
                year=2030,
                value=tonnes,
                unit="t",
                estimate_flag=True,
                source_id="nbs_2021_table13_13",
                method="production_equals_local_demand; unchanged2020; "
                + ("source_blank_explicit_zero_scenario" if missing else "observed2020_production"),
            )
        )
        for route, gemroute in [("BF-BOF", "BOF"), ("scrap-EAF", "EAF")]:
            key = (province, gemroute)
            if key not in caps and missing_policy != "explicit_zero_scenario":
                raise ValueError("GEM missing province requires explicit policy: " + province)
            capacity.append(
                dict(
                    province=province,
                    year=2030,
                    unit="t/year",
                    route=route,
                    existing_tpy=caps.get(key, 0.0),
                    estimate_flag=True,
                    source_id="gem_2026_province_capacity",
                    method="2026 operating capacity retained to2030; EAF is not necessarily scrap-only; missing capacity explicit zero scenario"
                    if key not in caps
                    else "2026 capacity retained to2030; EAF mapped to scrap route as scenario, not observed feedstock",
                )
            )
    return sector_rows, demand, capacity


def main():
    """Parse command-line input paths and write the selected generated outputs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annual-totals", type=Path, required=True)
    parser.add_argument(
        "--assumed-gross-steel-electricity-mwh-per-t",
        type=float,
        required=True,
        help="Explicit scenario input; must exclude electrolysis and match removed load boundary",
    )
    parser.add_argument(
        "--missing-policy", choices=["fail", "explicit_zero_scenario"], default="fail"
    )
    parser.add_argument("--evidence", type=Path, default=EVIDENCE)
    parser.add_argument("--output", type=Path, default=DERIVED / "demo")
    args = parser.parse_args()
    with args.annual_totals.open() as f:
        raw = list(csv.DictReader(f))
    totals = {r["province"]: float(r["annual_total_mwh"]) for r in raw}
    if len(totals) != len(raw):
        raise ValueError("Duplicate province totals")
    sectors, demand, caps = generate(
        totals, args.assumed_gross_steel_electricity_mwh_per_t, args.missing_policy, args.evidence
    )
    args.output.mkdir(parents=True, exist_ok=True)
    for name, rows in [
        ("demo_sector_electricity_2030.csv", sectors),
        ("demo_steel_demand_2030.csv", demand),
        ("demo_existing_capacity_2030.csv", caps),
    ]:
        with (args.output / name).open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


if __name__ == "__main__":
    main()
