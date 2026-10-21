"""Configuration and network adapters for explicit industrial electricity demand."""

from dataclasses import fields
from hashlib import sha256
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

if __package__:
    from .industry_loads import split_industry_loads
    from .industry_model import SteelRoute, add_steel_industry
else:
    from industry_loads import split_industry_loads
    from industry_model import SteelRoute, add_steel_industry


def industry_mode(config):
    """Return a validated mode; a nonempty configuration does not enable industry."""
    options = config.get("sectors", {}).get("industry", {})
    if not isinstance(options, dict):
        raise ValueError("sectors.industry must be a mapping with mode")
    mode = options.get("mode", "off")
    mode = "fixed_load" if mode == "fixed" else mode
    if mode not in {"off", "fixed_load", "endogenous"}:
        raise ValueError("industry mode must be off, fixed_load or endogenous")
    return mode


def ev_enabled(config):
    """Inspect the enabled flag, not the truthiness of its containing mapping."""
    options = config.get("sectors", {}).get("electric_vehicles", {})
    if not isinstance(options, dict):
        raise ValueError("sectors.electric_vehicles must be a mapping with enabled")
    enabled = options.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError("electric_vehicles.enabled must be a YAML boolean")
    return enabled


def sectors_enabled(config):
    """Whether the workflow needs a sector network, independently of EV activity."""
    mode = industry_mode(config)
    return ev_enabled(config) or mode != "off"


def sector_input_paths(config, derived_data):
    """Return only the file dependencies of enabled sectors/categories.

    Wildcards are left intact for Snakemake. All paths are project-root relative
    unless absolute; industry input files are explicit processed data products.
    """
    paths = {}
    if ev_enabled(config):
        transport = config["sectors"]["electric_vehicles"].get("transport", {})
        for category in ("passenger", "freight"):
            if transport.get(f"{category}_bev", {}).get("enable", False):
                paths[f"transport_demand_{category}"] = (
                    f"{derived_data}/transport/charging_demand_{category}_{{planning_horizons}}.csv"
                )
    mode = industry_mode(config)
    if mode == "off":
        return paths
    options = config["sectors"]["industry"]
    required = {"industry_sector_demand": options.get("annual_sector_demand")}
    paths["elec_load"] = f"{derived_data}/load/regio_hrly_ac_load_{{planning_horizons}}.h5"
    if mode == "endogenous":
        steel = options.get("steel", {})
        required.update({f"industry_{name}": steel.get(name) for name in
                         ("annual_demand", "capacities", "resources", "routes", "inventory")})
        selected = config.get("scenario", {}).get("co2_pathway")
        if isinstance(selected, str):
            selected = [selected]
        reductions = any(
            value.get("control") in {"reduction", "budget_from_reduction"}
            for name, value in config.get("co2_scenarios", {}).items()
            if selected is None or name in selected
        )
        if reductions:
            required["industry_carbon_baseline"] = options.get("carbon_baseline")
    for name, path in required.items():
        if not isinstance(path, str) or not path.strip():
            raise ValueError(f"Enabled industry requires an explicit {name} input path")
        paths[name] = path
    return paths


def _read_year_table(path, year, required, mapping):
    frame = pd.read_csv(path)
    if not {"year", "province", *required}.issubset(frame.columns) or frame.empty:
        raise ValueError(f"{path}: missing required columns or empty table")
    if frame[["year", "province", *required]].isna().any().any():
        raise ValueError(f"{path}: missing required values")
    if not pd.to_numeric(frame.year, errors="coerce").eq(year).all():
        raise ValueError(f"{path}: year must equal planning year; project inputs explicitly upstream")
    frame["province"] = frame.province.map(lambda p: mapping.get(p, p))
    return frame


def _provincial_quantity(path, year, provinces, mapping):
    frame = _read_year_table(path, year, ["value", "unit"], mapping)
    if not frame.unit.eq("t").all():
        raise ValueError(f"{path}: physical steel quantities require unit t")
    if frame.province.duplicated().any() or set(frame.province) != set(provinces):
        raise ValueError(f"{path}: need one row per electricity province")
    result = pd.to_numeric(frame.set_index("province").value, errors="raise").reindex(provinces)
    if not np.isfinite(result).all() or (result < 0).any():
        raise ValueError(f"{path}: quantities must be finite and nonnegative")
    return result


def _steel_inputs(paths, options, year, provinces, mapping):
    steel = options.get("steel", {})
    currency = steel.get("currency")
    if not isinstance(currency, str) or not currency.strip():
        raise ValueError("steel.currency must explicitly match the energy network's price basis")
    inventory_cost = steel.get("inventory_annual_cost_per_t")
    if inventory_cost is None or not np.isfinite(float(inventory_cost)) or float(inventory_cost) < 0:
        raise ValueError("Provide an explicit finite nonnegative inventory_annual_cost_per_t")
    demand = _provincial_quantity(paths["industry_annual_demand"], year, provinces, mapping)
    inventory = _provincial_quantity(paths["industry_inventory"], year, provinces, mapping)
    capacities = _read_year_table(paths["industry_capacities"], year,
                                  ["route", "existing_tpy", "new_max_tpy", "unit"], mapping)
    if not capacities.unit.eq("t/year").all():
        raise ValueError("Capacity input unit must be t/year")
    resources = _read_year_table(paths["industry_resources"], year,
                                 ["resource", "annual_limit", "marginal_cost", "unit", "currency"], mapping)
    expected_units = resources.resource.map({"ore": "t", "scrap": "t", "coal": "MWh_LHV", "gas": "MWh_LHV"})
    if expected_units.isna().any() or not resources.unit.eq(expected_units).all():
        raise ValueError("Resource units must be t for ore/scrap or MWh_LHV for coal/gas")
    if not resources.currency.eq(currency).all():
        raise ValueError("Resource currency/price basis differs from steel.currency")
    if not set(resources.province).issubset(provinces):
        raise ValueError("Unknown province in resource inputs")
    with open(paths["industry_routes"]) as stream:
        route_data = yaml.safe_load(stream)
    if not isinstance(route_data, dict) or route_data.get("year") != year or route_data.get("currency") != currency:
        raise ValueError("Route YAML must declare the planning year and common currency")
    route_rows = route_data.get("routes")
    if not isinstance(route_rows, list) or not route_rows:
        raise ValueError("Route YAML needs a nonempty routes list")
    parameter_names = {field.name for field in fields(SteelRoute)}
    routes = []
    for row in route_rows:
        if not isinstance(row, dict) or not parameter_names.issubset(row):
            raise ValueError("Every route must explicitly supply all SteelRoute parameters, including flexibility")
        unknown = set(row) - parameter_names - {"source_id", "estimate_flag", "notes"}
        if unknown:
            raise ValueError(f"Unknown route parameters: {sorted(unknown)}")
        route = SteelRoute(**{name: row[name] for name in parameter_names})
        route.validate()
        routes.append(route)
    return dict(annual_demand_t=demand, capacities=capacities, routes=routes, resources=resources,
                currency=currency, inventory_t=inventory,
                inventory_annual_cost_per_t=float(inventory_cost))


def _read_annual_load(path):
    with pd.HDFStore(path, mode="r") as store:
        total = store["load"]
        weights = store["weights"] if "/weights" in store.keys() else None
    if isinstance(weights, pd.DataFrame):
        if "generators" in weights:
            weights = weights["generators"]
        elif len(weights.columns) == 1:
            weights = weights.iloc[:, 0]
        else:
            raise ValueError("HDF weights require a Series or a generators column")
    return total, weights


def _replace_electricity_loads(n, split):
    if n.meta.get("industry_loads"):
        raise ValueError("Industrial load decomposition has already been attached")
    provinces = split.total_load_mw.columns
    if not n.snapshots.isin(split.total_load_mw.index).all():
        raise ValueError("Network snapshots are missing from the complete annual electricity profile")
    if not provinces.isin(n.buses.index).all() or not n.buses.loc[provinces, "carrier"].eq("AC").all():
        raise ValueError("Electricity provinces must match existing AC buses")
    if not provinces.isin(n.loads.index).all() or not n.loads.loc[provinces, "bus"].equals(pd.Series(provinces, index=provinces, name="bus")):
        raise ValueError("Expected exactly named original provincial electricity Loads")
    expected = split.total_load_mw.loc[n.snapshots]
    original = n.get_switchable_as_dense("Load", "p_set").loc[n.snapshots, provinces]
    if not np.allclose(original, expected, rtol=1e-9, atol=1e-6):
        raise ValueError("Original provincial Load differs from the annual HDF baseline; refusing replacement")
    fixed = split.fixed_loads_mw.loc[n.snapshots]
    names = [f"{province} electricity {sector}" for province, sector in fixed.columns]
    if n.loads.index.isin(names).any():
        raise ValueError("Sector electricity load names already exist")
    # All replacements are validated before removing any legacy demand.
    n.remove("Load", provinces)
    for (province, sector), name in zip(fixed.columns, names):
        carrier = f"electricity {sector}"
        if carrier not in n.carriers.index:
            n.add("Carrier", carrier)
        n.add("Load", name, bus=province, carrier=carrier, p_set=fixed[province, sector])
    steel = split.steel_baseline_mw.loc[n.snapshots]
    fixed_by_province = fixed.T.groupby(level="province").sum().T.reindex(columns=provinces)
    removed = steel if split.mode == "endogenous" else steel * 0
    reconstructed = fixed_by_province + removed
    weights = n.snapshot_weightings.generators
    n.meta["industry_loads"] = {
        "version": 1, "mode": split.mode, "planning_year": int(split.planning_year),
        "allocation_method": "constant annual shares of the full provincial electricity shape",
        "original_load_names": list(provinces), "fixed_load_names": names,
        "annual_total_mwh": split.annual_total_mwh.to_dict(),
        "annual_steel_baseline_mwh": split.annual_targets_mwh.steel.to_dict(),
        "original_period_mwh": original.mul(weights, axis=0).sum().to_dict(),
        "fixed_period_mwh": fixed_by_province.mul(weights, axis=0).sum().to_dict(),
        "removed_steel_period_mwh": removed.mul(weights, axis=0).sum().to_dict(),
        "reconstruction_max_abs_mw": float((reconstructed - original).abs().to_numpy().max()),
        "baseline_snapshots": [timestamp.isoformat() for timestamp in n.snapshots],
        "steel_baseline_mw": {province: steel[province].tolist() for province in provinces},
    }


def add_configured_industry(n, config, *, planning_year, inputs):
    """Return a sector-enabled copy, preserving the input network on any failure.

    Off mode returns the original network and never reads industry files. Inputs
    use names returned by sector_input_paths. Full-year splitting always precedes
    selection of the network's solve snapshots. Metadata retains the actual
    steel baseline time series, integral reconciliation, and source checksums.
    """
    mode = industry_mode(config)
    if mode == "off":
        return n
    options = config["sectors"]["industry"]
    mapping = options.get("province_mapping", {})
    if not isinstance(mapping, dict):
        raise ValueError("industry.province_mapping must be an explicit alias mapping")
    paths = {key: str(path).format(planning_horizons=planning_year) for key, path in dict(inputs).items()
             if key == "elec_load" or key.startswith("industry_")}
    total, weights = _read_annual_load(paths["elec_load"])
    annual = pd.read_csv(paths["industry_sector_demand"])
    split = split_industry_loads(total, annual, planning_year=planning_year, mode=mode,
                                 snapshot_weightings=weights, province_mapping=mapping)
    model_inputs = _steel_inputs(paths, options, planning_year, total.columns, mapping) if mode == "endogenous" else None
    result = n.copy()
    _replace_electricity_loads(result, split)
    if model_inputs is not None:
        add_steel_industry(result, **model_inputs)
    result.meta["industry_loads"]["sources"] = {
        key: {"path": str(Path(path)), "sha256": sha256(Path(path).read_bytes()).hexdigest()}
        for key, path in paths.items()
    }
    return result
