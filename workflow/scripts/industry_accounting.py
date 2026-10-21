"""Unit-separated carbon, electricity and steel validation reports."""

import numpy as np
import pandas as pd
from pypsa.descriptors import get_switchable_as_dense as get_as_dense

from industry_model import chronological_hours, steel_dispatch


def steel_baseline_emissions(path, provinces, year=2020):
    """Read an evidenced route-production reconstruction, never a capacity sum.

    CSV rows: province, year, route, production_t, direct_co2_t_per_t, source_id,
    method. Include explicit documented zero observations for inactive provinces.
    Only direct emissions belong here; electricity/H2 remain in the energy base.
    """
    frame = pd.read_csv(path)
    required = {"province", "year", "route", "production_t", "direct_co2_t_per_t", "source_id", "method"}
    if not required.issubset(frame):
        raise ValueError(f"Steel baseline is missing columns {required - set(frame)}")
    if frame.empty or frame[list(required)].isna().any().any():
        raise ValueError("Steel baseline contains missing observations or evidence")
    if not frame.year.eq(year).all():
        raise ValueError(f"Steel carbon baseline must use {year} production")
    if frame.duplicated(["province", "route"]).any():
        raise ValueError("Steel baseline has duplicate province-route observations")
    if set(frame.province) != set(provinces):
        raise ValueError("Steel baseline must explicitly cover every model province")
    for column in ("source_id", "method", "route"):
        if frame[column].astype(str).str.strip().eq("").any():
            raise ValueError(f"Steel baseline needs nonempty {column}")
    values = frame[["production_t", "direct_co2_t_per_t"]].astype(float)
    if not np.isfinite(values).all().all() or (values < 0).any().any():
        raise ValueError("Invalid baseline production or direct emissions coefficient")
    return float((values.production_t * values.direct_co2_t_per_t).sum())


def electrical_consumption_links(n):
    """AC-input conversion links, excluding AC-to-AC transmission."""
    return n.links.index[(n.links.bus0.map(n.buses.carrier) == "AC") &
                         (n.links.bus1.map(n.buses.carrier) != "AC")]


def fixed_electricity_load(n):
    indices = n.loads.index[n.loads.bus.map(n.buses.carrier).eq("AC")]
    return get_as_dense(n, "Load", "p_set").reindex(columns=indices).sum(axis=1)


def electricity_consumption_by_province(n):
    """Solved MW of fixed AC demand plus conversion inputs, grouped by AC bus.

    Includes electrolysis, process electricity, EV charging and heating conversion.
    Never adds material Loads in t/h to energy demand.
    """
    loads = n.loads.index[n.loads.bus.map(n.buses.carrier).eq("AC")]
    fixed = get_as_dense(n, "Load", "p_set").reindex(columns=loads).T.groupby(n.loads.bus).sum().T
    links = electrical_consumption_links(n)
    conversion = n.links_t.p0.reindex(columns=links).T.groupby(n.links.bus0).sum().T
    return fixed.add(conversion, fill_value=0)


def primary_energy_emissions(n):
    """Recompute PyPSA 0.35 primary_energy CO2 accounting from a solved network."""
    emissions = n.carriers.co2_emissions
    gens = n.generators.index[n.generators.carrier.map(emissions).fillna(0).ne(0)]
    efficiency = get_as_dense(n, "Generator", "efficiency", inds=gens)
    gen = n.generators_t.p.reindex(columns=gens).div(efficiency)
    gen = gen.mul(n.generators.loc[gens, "carrier"].map(emissions), axis=1)
    by_generator = gen.mul(n.snapshot_weightings.generators, axis=0).sum()
    total = float(by_generator.sum())
    for table, timeseries, cyclic, state, initial in (
        (n.stores, n.stores_t, "e_cyclic", "e", "e_initial"),
        (n.storage_units, n.storage_units_t, "cyclic_state_of_charge", "state_of_charge", "state_of_charge_initial"),
    ):
        selected = table.index[~table[cyclic] & table.carrier.map(emissions).fillna(0).ne(0)]
        if len(selected):
            depletion = table.loc[selected, initial] - timeseries[state].loc[:, selected].iloc[-1]
            total += float((depletion * table.loc[selected, "carrier"].map(emissions)).sum())
    return total, by_generator


def validate_industry_solution(n, tolerance=1e-5):
    """Fail on unit/accounting residuals; return JSON-serializable diagnostics."""
    if not n.meta.get("industry"):
        return {}
    step, hours = chronological_hours(n)
    q, electricity = steel_dispatch(n)
    if q.empty or not np.isfinite(q).all().all():
        raise ValueError("Missing finite solved steel dispatch")
    route_specs = {r["name"]: r for r in n.meta["industry"]["routes"]}
    records = n.meta["industry"]["links"]
    residuals = {}
    metrics = []
    for record in records:
        name = record["name"]
        link = n.links.loc[name]
        p = electricity[name].to_numpy()
        cap = float(link.p_nom_opt)
        delta = p - np.roll(p, 1)
        violations = np.concatenate([
            -p, p - cap, float(link.p_min_pu) * cap - p,
            delta - record["ramp_up"] * cap,
            -delta - record["ramp_down"] * cap,
            [cap - float(link.p_nom_max)],
        ])
        residuals[f"{name}:operation_MW"] = float(max(0, violations.max()))
        metrics.append({"province": record["province"], "route": record["route"],
                        "vintage": record["vintage"],
                        "capacity_tpy": cap / record["electricity_mwh_per_t"] * record["capacity_basis_hours"],
                        "production_t": float(q[name].sum() * step),
                        "direct_electricity_mwh": float(electricity[name].sum() * step)})
    for province, annual in n.meta["industry"]["annual_demand_t"].items():
        selected = [r for r in records if r["province"] == province]
        names = [r["name"] for r in selected]
        product = q[names].sum(axis=1)
        demand = annual / 8760.0
        stock = n.stores_t.e[f"{province} steel inventory"].to_numpy()
        capacity = n.stores.at[f"{province} steel inventory", "e_nom_opt"]
        maximum = n.stores.at[f"{province} steel inventory", "e_nom_max"]
        residuals[f"{province}:material_t"] = float(np.abs(stock - np.roll(stock, 1) - (product.to_numpy() - demand) * step).max())
        residuals[f"{province}:inventory_t"] = float(max(0, -stock.min(), stock.max() - capacity, capacity - maximum))
        expected = sum(q[r["name"]] * route_specs[r["route"]]["direct_co2_t_per_t"] for r in selected)
        actual = n.generators_t.p[f"{province} steel emissions"]
        residuals[f"{province}:direct_CO2_t_per_h"] = float(np.abs(actual - expected).max())
    resource_mask = n.generators.carrier.str.startswith("steel ") & n.generators.carrier.str.endswith(" supply")
    for name in n.generators.index[resource_mask]:
        used = float((n.generators_t.p[name] * n.snapshot_weightings.generators).sum())
        limit = n.generators.at[name, "e_sum_max"]
        residuals[f"{name}:resource_fraction"] = max(0, used - limit) / max(1, limit)
    total_co2, by_generator = primary_energy_emissions(n)
    for name, cap in n.global_constraints.iterrows():
        if cap.type == "primary_energy" and cap.carrier_attribute == "co2_emissions" and cap.sense == "<=":
            residuals[f"{name}:CO2_fraction"] = max(0, total_co2 - cap.constant) / max(1, abs(cap.constant))
    failures = {k: v for k, v in residuals.items() if not np.isfinite(v) or v > tolerance}
    if failures:
        raise ValueError(f"Industry solution failed physical checks: {failures}")
    direct = by_generator.reindex([f"{p} steel emissions" for p in n.meta["industry"]["annual_demand_t"]]).sum()
    return {"period_hours": hours, "annual_result": hours == 8760,
            "total_co2_t": total_co2, "steel_direct_co2_t": float(direct),
            "other_primary_energy_co2_t": total_co2 - float(direct),
            "routes": metrics, "residuals": residuals}
