#!/usr/bin/env python3
"""Reuse PIK inputs for independent industry validation; never write to the source checkout.

Pass complete PIK configuration first, then explicit industry/scenario overrides.
The default action prepares and exports a network; --solve explicitly runs the solver.
Existing network capital costs must already correspond to its physical time window.
"""

import argparse
from copy import deepcopy
from hashlib import sha256
import json
import logging
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pypsa
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "workflow/scripts"))
from _helpers import ConfigManager  # noqa: E402
from add_sectors import add_configured_sectors  # noqa: E402
from industry_adapter import sector_input_paths  # noqa: E402
from solve_network import (  # noqa: E402
    add_fuel_subsidies, calc_nuclear_expansion_limit, prepare_network,
    set_transmission_limit, solve_network,
)


def merge(base, overlay):
    """Merge explicitly supplied YAML overlays, preserving nested configuration."""
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            merge(base[key], value)
        else:
            base[key] = deepcopy(value)
    return base


def source_paths(value, source_root):
    """Resolve legacy resource references against the read-only input checkout."""
    if isinstance(value, dict):
        return {k: source_paths(v, source_root) for k, v in value.items()}
    if isinstance(value, list):
        return [source_paths(v, source_root) for v in value]
    if isinstance(value, str) and value.startswith("resources/"):
        return str(source_root / value)
    return value


def build_inputs(config, source_root, year, annual_load):
    """The same named inputs as the normal prepare_networks rule, without producers."""
    derived = source_root / "resources/derived_data"
    cutout = derived / f"cutout_{config['atlite']['cutout_name']}"
    scenario_inputs = Path(annual_load).parent.parent
    paths = {
        "elec_load": str(annual_load),
        "heat_demand_profile": str(scenario_inputs / f"heating-cutout_{config['atlite']['cutout_name']}/heat_demand_profile_{year}.h5"),
        "central_fraction": str(source_root / "resources/data/heating/DH_city_town_2020.h5"),
        "solar_thermal_name": str(cutout / f"heating/solar_thermal-{config['solar_thermal_angle']}.h5"),
        "cop_name": str(cutout / "heating/hp_cop.h5"),
        "intraday_profiles": str(source_root / "resources/data/heating/heat_load_profile_DK_AdamJensen.csv"),
        "tech_costs": str(Path(config["paths"]["costs_dir"]) / f"costs_{year}.csv"),
        "province_shape": str(derived / "province_shapes/CHN_adm1.shp"),
        "biomass_potential": str(derived / "p_nom/biomass_potential.h5"),
        "installed_capacities": str(scenario_inputs / "existing_infrastructure/capacities.csv"),
    }
    for tech, options in config["renewable"].items():
        label = "_".join(f"{key}{value}" for key, value in options["resource_classes"].items())
        paths[f"profile_{tech}"] = str(cutout / f"profile_{tech}-{label}.nc")
    return paths


def build_annual_network(config, inputs, year, output):
    """Run normal PIK construction functions on 2030's contiguous nonleap calendar."""
    import prepare_network as builder
    import add_existing_baseyear as existing
    from add_electricity import load_costs, sanitize_carriers

    if pd.Timestamp(year, 12, 31).is_leap_year:
        raise ValueError("This validation runner requires an explicit nonleap planning calendar")
    if config["run"].get("is_remind_coupled", False):
        raise ValueError("Annual resource reuse currently supports independent PIK planning only")
    snapshots = pd.date_range(f"{year}-01-01", f"{year}-12-31 23:00", freq="h")
    config["snapshots"].update(start="01-01 00:00", end="12-31 23:00", freq="1h",
                               frequency=1., bounds="both", end_year_plus1=False)
    builder.snakemake = SimpleNamespace(wildcards={"planning_horizons": year})
    builder.config = config  # Legacy helper functions read the script-level configuration.
    builder.snapshots = snapshots
    builder.yr = year
    costs = load_costs(inputs["tech_costs"], config["costs"], config["electricity"], year, 1.)
    builder.costs = costs
    builder.n_years = 1.
    biomass = pd.read_hdf(inputs["biomass_potential"]) if config["add_biomass"] else None
    n = builder.prepare_network(config, costs, snapshots, biomass, paths=inputs)
    sanitize_carriers(n, config)
    n.export_to_netcdf(output / f"greenfield_{year}.nc")
    costs.to_csv(output / f"costs_{year}.csv")
    if config["existing_capacities"].get("add", False):
        existing.snakemake = SimpleNamespace(input=SimpleNamespace(cop_name=inputs["cop_name"]),
                                             wildcards=SimpleNamespace(planning_horizons=year))
        capacities = existing.filter_brownfield_capacities(
            pd.read_csv(inputs["installed_capacities"], index_col=0), year)
        vre = ["onwind", "offwind", "solar"]
        is_vre = capacities.Tech.isin(vre) | capacities.Fueltype.isin(vre)
        vres = existing.add_existing_vre_capacities(n, costs, capacities.loc[is_vre], config)
        installed = pd.concat([capacities.loc[~is_vre], vres])
        existing.add_power_capacities_installed_before_baseyear(n, costs, config, installed)
    n.meta["validation_weather_mapping"] = {
        "method": "PIK shift_profile_to_planning_year: remove source Feb29, replace year preserving month/day/hour",
        "source_weather_year": config["atlite"]["cutouts"][config["atlite"]["cutout_name"]]["weather_year"],
        "planning_year": year, "physical_hours": len(snapshots),
    }
    n.export_to_netcdf(output / f"brownfield_{year}.nc")
    return n


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, nargs="+", required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--network", type=Path, help="Unsolved PIK prenetwork, already including brownfield if enabled")
    choice.add_argument("--build-annual", action="store_true")
    parser.add_argument("--annual-load", type=Path, required=True)
    parser.add_argument("--nuclear-baseline-network", type=Path,
                        help="Optional existing base-year network to preserve PIK nuclear expansion baseline")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--year", type=int, default=2030)
    parser.add_argument("--co2-pathway", required=True)
    parser.add_argument("--budget-input-hours", type=float,
                        help="Explicit time basis of supplied budget values: 8760 annual, 72 for old three-day run config")
    parser.add_argument("--solve", action="store_true")
    parser.add_argument("--check-resources", action="store_true", help="Audit annual construction files without building")
    args = parser.parse_args(argv)
    source_root = args.source_root.resolve()
    output = args.output_dir.resolve()
    if not output.is_relative_to(ROOT / "results") or output.is_relative_to(source_root):
        raise ValueError("Validation output must be inside this worktree's results, outside source checkout")
    output.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    config = {}
    for path in args.config:
        merge(config, yaml.safe_load(path.read_text()))
    config = source_paths(config, source_root)
    config["scenario"].update(planning_horizons=[args.year], co2_pathway=[args.co2_pathway])
    if config["run"].get("is_test", False):
        raise ValueError("Validation must not use mock/test solving")
    if config["solving"]["options"].get("nhours") or config["solving"]["options"].get("load_shedding"):
        raise ValueError("Validation forbids nhours annual reweighting and load shedding")
    carbon = config["co2_scenarios"][args.co2_pathway]
    if carbon["control"] == "budget":
        if args.budget_input_hours is None or not 0 < args.budget_input_hours <= 8760:
            raise ValueError("Budget input requires explicit --budget-input-hours in (0,8760]")
        carbon["pathway"] = {year: value * 8760 / args.budget_input_hours for year, value in carbon["pathway"].items()}
    config = ConfigManager(config).handle_scenarios()
    if args.nuclear_baseline_network:
        baseline = pypsa.Network(args.nuclear_baseline_network)
        config.setdefault("nuclear_reactors", {})["base_capacity"] = float(
            baseline.generators.loc[baseline.generators.carrier.eq("nuclear"), "p_nom"].sum())
    paths = build_inputs(config, source_root, args.year, args.annual_load.resolve())
    resource_audit = {name: {"path": path, "exists": Path(path).is_file()} for name, path in paths.items()}
    (output / "resource_audit.json").write_text(json.dumps(resource_audit, indent=2))
    (output / "annual_config.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    if args.check_resources:
        missing = [name for name, item in resource_audit.items() if not item["exists"]]
        if missing:
            raise FileNotFoundError(f"Annual construction inputs missing: {missing}")
        return 0
    if args.build_annual:
        n = build_annual_network(config, paths, args.year, output)
        network_path = output / f"brownfield_{args.year}.nc"
    else:
        network_path = args.network.resolve()
        n = pypsa.Network(network_path)
    expected = pd.date_range(n.snapshots[0], n.snapshots[-1], freq="h")
    if not n.snapshots.equals(expected) or not np.allclose(n.snapshot_weightings, 1.):
        raise ValueError("Validation network must have continuous physical hourly snapshots with weights=1")
    if n.snapshots.year.min() != args.year or n.snapshots.year.max() != args.year:
        raise ValueError("Network must already use the specified planning-year calendar")
    if not n.global_constraints.empty:
        raise ValueError("Expected a pre-solve network without existing global constraints")
    config["snapshots"].update(start=n.snapshots[0].strftime("%m-%d %H:%M"),
                               end=n.snapshots[-1].strftime("%m-%d %H:%M"), freq="1h",
                               frequency=1., bounds="both", end_year_plus1=False)
    # Record the actual physical calendar, including when an existing network is reused.
    (output / "annual_config.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    inputs = sector_input_paths(config, str(Path(paths["elec_load"]).parent.parent))
    inputs["elec_load"] = paths["elec_load"]
    n = add_configured_sectors(n, config, planning_year=args.year, inputs=inputs)
    period_hours = len(n.snapshots)
    # Core prepare_network scales annual budgets for endogenous industry. Legacy
    # off/fixed_load expects a period budget; scale exactly once for those modes.
    solve_config = deepcopy(config)
    carbon = solve_config["co2_scenarios"][args.co2_pathway]
    if not n.meta.get("industry") and str(carbon["control"]).startswith("budget"):
        carbon["pathway"] = {year: value * period_hours / 8760 for year, value in carbon["pathway"].items()}
    n = prepare_network(n, solve_config["solving"]["options"], solve_config, args.year, args.co2_pathway)
    subsidies = solve_config.get("subsidies", {})
    if subsidies.get("enabled", bool(subsidies)):
        add_fuel_subsidies(n, {k: v for k, v in subsidies.items() if k != "enabled"}, planning_year=args.year)
    limits = solve_config["lines"].get("expansion", {"transmission_limit": "copt", "base_year": 2020})
    transmission = limits.get("transmission_limit", "copt")
    set_transmission_limit(n, kind=transmission[0], factor=transmission[1:],
                           n_years=args.year - int(limits.get("base_year", 2020)))
    nuclear = calc_nuclear_expansion_limit(n, solve_config, args.year, str(network_path))
    if nuclear is not None:
        solve_config["nuclear_max_capacity"] = float(nuclear)
    n.meta["pik_validation"] = {
        "source_network": str(network_path), "source_sha256": sha256(network_path.read_bytes()).hexdigest(),
        "period_hours": period_hours, "input_budget_hours": args.budget_input_hours,
        "config_sources": [str(p.resolve()) for p in args.config],
        "stage": "prepared", "warning": "Short windows validate integration, not annual planning results",
    }
    (output / "solve_config.yaml").write_text(yaml.safe_dump(solve_config, sort_keys=False))
    n.export_to_netcdf(output / f"prepared_{args.year}.nc")
    if args.solve:
        n = solve_network(n, config=solve_config, solving=solve_config["solving"], opts=[],
                          log_fn=str(output / "solver.log"))
        if n.model.status != "ok" or n.model.termination_condition != "optimal":
            raise RuntimeError(f"Expected optimal solve, got {n.model.status}/{n.model.termination_condition}")
        if not np.isfinite(n.objective):
            raise RuntimeError("No finite solver objective")
        n.meta["pik_validation"].update(stage="solved", solver=solve_config["solving"]["solver"],
                                        status=n.model.status, termination_condition=n.model.termination_condition)
        n.export_to_netcdf(output / f"solved_{args.year}.nc")
    (output / "validation.json").write_text(json.dumps(n.meta, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
