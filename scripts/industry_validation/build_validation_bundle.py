"""Build traceable, explicitly approximate input tables for workflow validation.

Uses real provincial production/capacity and a complete existing electricity HDF.
Every derived row is an estimate. The resulting scenario is deliberately labeled
engineering_validation_only; it is not a calibrated research scenario.
"""
import argparse
from dataclasses import fields
from hashlib import sha256
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "workflow/scripts"))
sys.path.insert(0, str(ROOT / "workflow/scripts/industry_data"))
from industry_model import SteelRoute
from make_demo_inputs import generate


def build(load_path, assumption_path, output):
    assumptions = yaml.safe_load(assumption_path.read_text())
    if assumptions["status"] != "engineering_validation_only" or assumptions["year"] != 2030:
        raise ValueError("This builder is only for explicitly labeled 2030 validation")
    frame = pd.read_hdf(load_path, "load")
    expected = pd.date_range("2030-01-01", periods=8760, freq="h")
    if not frame.index.equals(expected) or not frame.columns.is_unique:
        raise ValueError("Validation input requires a complete regular hourly non-leap year")
    if not np.isfinite(frame.to_numpy()).all() or (frame < 0).any().any():
        raise ValueError("Electricity profile must contain only finite nonnegative values")
    totals = frame.sum()
    specs = assumptions["routes"]
    by_name = {r["name"]: r for r in specs}
    # Generate top-level sector proxy shares; overwrite steel with route-weighted
    # gross electricity below, keeping all provenance explicit.
    sectors, demand, existing = generate(totals.to_dict(), by_name["BF-BOF"]["electricity_mwh_per_t"],
                                         assumptions["missing_production_policy"])
    demand = pd.DataFrame(demand)
    demand_values = demand.set_index("province")["value"]
    existing = pd.DataFrame(existing).set_index(["province", "route"])
    sectors = pd.DataFrame(sectors)
    baselines, capacities, resources, inventory = [], [], [], []
    routes = []
    currency = assumptions["currency"]
    for spec in specs:
        rate, life = assumptions["discount_rate"], spec["lifetime_years"]
        annuity = rate / (1 - (1 + rate) ** -life) if rate else 1 / life
        values = {f.name: spec[f.name] for f in fields(SteelRoute)
                  if f.name not in {"new_annual_cost_per_tpy", "active_annual_cost_per_tpy"}}
        values.update(new_annual_cost_per_tpy=spec["capex_per_tpy"] * (annuity + spec["fom_fraction"]),
                      active_annual_cost_per_tpy=spec["capex_per_tpy"] * spec["fom_fraction"])
        SteelRoute(**values).validate()
        routes.append(dict(**values, source_id=spec["source_id"], estimate_flag=True, notes=spec["notes"]))
    for province, tonnes in demand_values.items():
        bof = float(existing.loc[(province, "BF-BOF"), "existing_tpy"])
        eaf = float(existing.loc[(province, "scrap-EAF"), "existing_tpy"])
        share = eaf / (bof + eaf) if bof + eaf else 0.0
        baseline_electricity = 0.0
        for name, fraction in (("BF-BOF", 1-share), ("scrap-EAF", share)):
            spec = by_name[name]
            baseline_electricity += tonnes * fraction * spec["electricity_mwh_per_t"]
            baselines.append(dict(province=province, year=2020, route=name, production_t=tonnes * fraction,
                                  direct_co2_t_per_t=spec["direct_co2_t_per_t"],
                                  source_id="nbs_2021_table13_13;gem_2026_province_capacity;validation_assumptions",
                                  estimate_flag=True, method=assumptions["assumptions"]["baseline"]))
        mask = sectors.province.eq(province) & sectors.sector.eq("steel")
        sectors.loc[mask, "value"] = baseline_electricity
        sectors.loc[mask, "source_id"] = "nbs_2021_table13_13;gem_2026_province_capacity;validation_assumptions"
        sectors.loc[mask, "method"] = assumptions["assumptions"]["baseline"]
        industry_total = sectors.loc[sectors.province.eq(province) & sectors.sector.eq("industry"), "value"].iloc[0]
        if baseline_electricity > industry_total:
            raise ValueError(f"{province}: steel baseline exceeds proxy industry demand")
        for spec in specs:
            name = spec["name"]
            old = float(existing.loc[(province, name), "existing_tpy"]) if (province, name) in existing.index else 0.0
            h2 = name == "H2-DRI-EAF"
            capacities.append(dict(province=province, year=2030, route=name, existing_tpy=old,
                                   new_max_tpy=tonnes * assumptions["new_capacity_multiple_of_demand"], unit="t/year",
                                   source_id="validation_assumptions" if h2 else "gem_2026_province_capacity;validation_assumptions", estimate_flag=True,
                                   method="zero existing H2 steel and finite additions are explicit scenario choices; GEM does not supply H2 route capacity" if h2 else
                                          "retain 2026 capacity; finite explicit additions; EAF assumed scrap-fed"))
        for resource, price in assumptions["resource_prices"].items():
            suffix = "mwh" if resource in ("coal", "gas") else "t"
            factor = max(r[f"{resource}_{suffix}_per_t"] for r in specs)
            limit = tonnes * factor * assumptions["resource_capacity_multiple_of_demand"]
            if resource == "scrap":
                limit = tonnes * by_name["scrap-EAF"]["scrap_t_per_t"] * assumptions["scrap_fraction_of_crude_demand"]
            resources.append(dict(province=province, year=2030, resource=resource, annual_limit=limit,
                                  marginal_cost=price, unit="MWh_LHV" if suffix == "mwh" else "t", currency=currency,
                                  source_id="validation_assumptions", estimate_flag=True,
                                  method="finite engineering test envelope, not observed supply"))
        inventory.append(dict(province=province, year=2030, value=tonnes * assumptions["inventory_days"] / 365,
                              unit="t", source_id="validation_assumptions", estimate_flag=True))
    output.mkdir(parents=True, exist_ok=True)
    tables = {"sector_electricity_2030": sectors, "steel_demand_2030": demand,
              "steel_capacities_2030": pd.DataFrame(capacities), "steel_resources_2030": pd.DataFrame(resources),
              "steel_inventory_2030": pd.DataFrame(inventory), "steel_direct_co2_baseline_2020": pd.DataFrame(baselines)}
    for name, table in tables.items():
        table.to_csv(output / f"{name}.csv", index=False)
    (output / "steel_routes_2030.yaml").write_text(yaml.safe_dump(dict(year=2030, currency=currency, routes=routes), sort_keys=False))
    def relative(path):
        return str(path.resolve().relative_to(ROOT)) if path.resolve().is_relative_to(ROOT) else str(path.resolve())
    config = {"sectors": {"industry": {"mode": "endogenous",
               "annual_sector_demand": relative(output / "sector_electricity_2030.csv"),
               "carbon_baseline": relative(output / "steel_direct_co2_baseline_2020.csv"),
               "provenance_manifest": relative(output / "manifest.json"),
               "steel": {key: relative(output / filename) for key, filename in {
                   "annual_demand": "steel_demand_2030.csv", "capacities": "steel_capacities_2030.csv",
                   "resources": "steel_resources_2030.csv", "inventory": "steel_inventory_2030.csv",
                   "routes": "steel_routes_2030.yaml"}.items()}}}}
    config["sectors"]["industry"]["steel"].update(currency=currency,
                  inventory_annual_cost_per_t=assumptions["inventory_annual_cost_per_t"])
    (output / "config.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    inputs = [load_path, assumption_path, ROOT / "data/industry/processed/nbs_province_steel_production_2020.csv",
              ROOT / "data/industry/processed/gem_province_capacity_2026.csv", ROOT / "data/industry/processed/henan_sector_electricity_2024.csv"]
    code = [Path(__file__), ROOT / "workflow/scripts/industry_data/make_demo_inputs.py",
            ROOT / "workflow/scripts/industry_model.py", ROOT / "data/industry/sources/manifest.json"]
    manifest = dict(status=assumptions["status"], assumptions=assumptions,
                    sources=[dict(path=relative(p), sha256=sha256(p.read_bytes()).hexdigest()) for p in inputs],
                    implementation=[dict(path=relative(p), sha256=sha256(p.read_bytes()).hexdigest()) for p in code],
                    portability="The annual electricity HDF is an external PIK resource, not redistributed here. Supply --load with an equivalent complete 2030 hourly provincial HDF and regenerate this bundle; compare its SHA256 to reproduce this exact fixture.",
                    outputs={p.name: sha256(p.read_bytes()).hexdigest() for p in sorted(output.iterdir()) if p.suffix in {".csv", ".yaml"}})
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return config


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--load", type=Path, required=True)
    parser.add_argument("--assumptions", type=Path, default=ROOT / "config/industry.validation_assumptions.yaml")
    parser.add_argument("--output", type=Path, default=ROOT / "data/industry/validation")
    args = parser.parse_args()
    build(args.load, args.assumptions, args.output)
