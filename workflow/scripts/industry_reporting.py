"""Export validated industrial results without annualising short test periods.

Run as ``python workflow/scripts/industry_reporting.py solved.nc output_dir``.
Currency/price basis is inherited verbatim from ``n.meta['industry']['currency']``.
Route costs cover the production Link only. Resource supply costs are reported
separately; electricity, upstream hydrogen and emission prices are not allocated
to routes, so these tables are not a full system-objective decomposition.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from pypsa.descriptors import get_switchable_as_dense as get_as_dense

from industry_accounting import (
    electricity_consumption_by_province, validate_industry_solution,
)
from industry_model import chronological_hours, solved_output, steel_dispatch


def _integral(series, weights):
    return float(series.mul(weights).sum())


def _input_quantity(n, name, bus, coefficient, production, weights):
    """Read the solved physical input port; check it against process metadata."""
    ports = [c for c in n.links.columns if c.startswith("bus") and c[3:].isdigit()
             and n.links.at[name, c] == bus]
    if not ports:
        if coefficient != 0:
            raise ValueError(f"Missing input port {name}: {bus}")
        return 0.0
    if len(ports) != 1:
        raise ValueError(f"Ambiguous input port {name}: {bus}")
    actual = solved_output(n, "Link", f"p{ports[0][3:]}", [name]).iloc[:, 0]
    if not np.allclose(actual, production * coefficient, atol=1e-6, rtol=1e-7):
        raise ValueError(f"Process coefficient/dispatch mismatch {name}: {bus}")
    return _integral(actual, weights)


def export_industry_reports(n, output_dir):
    """Validate a solved network, write four CSVs plus an audit JSON, return paths.

    Capacity is a nominal annual rating, never a period production quantity.
    Utilisation = period tonnes / (capacity_tpy / rating_hours * period_hours).
    It is undefined (blank CSV) for zero selected capacity. Annual resource
    limits are reconstructed from the model's explicitly prorated period limits.
    Initial inventory means pre-first-interval stock; for cyclic stores it equals
    the terminal stock, which need not be zero unless the scenario constrains it.
    """
    if not n.meta.get("industry"):
        raise ValueError("Network has no industrial model metadata")
    checks = validate_industry_solution(n)
    step, hours = chronological_hours(n)
    industry = n.meta["industry"]
    currency = industry["currency"]
    provenance = industry.get("provenance", {
        "version": 1, "manifest_status": "not_provided", "data_status": "unknown",
        "manifest": None, "assumptions": {}, "input_coverage": {},
    })
    weights = n.snapshot_weightings.generators
    q, power = steel_dispatch(n)
    specs = {r["name"]: r for r in industry["routes"]}
    common = {"period_hours": hours, "annual_result": hours == 8760,
              "currency": currency, "data_status": provenance.get("data_status", "unknown"),
              "provenance_manifest_status": provenance.get("manifest_status", "not_provided")}
    link_cost = get_as_dense(n, "Link", "marginal_cost")
    route_rows = []
    for record in industry["links"]:
        name, province = record["name"], record["province"]
        spec, link = specs[record["route"]], n.links.loc[record["name"]]
        e = record["electricity_mwh_per_t"]
        h = record["capacity_basis_hours"]
        capacity_tph = float(link.p_nom_opt) / e
        tonnes = _integral(q[name], weights)
        row = dict(common, province=province, route=record["route"],
                   vintage=record["vintage"], component=name,
                   capacity_basis_hours=h, capacity_tpy=capacity_tph * h,
                   capacity_upper_bound_tpy=float(link.p_nom_max) / e * h,
                   installed_capacity_tph=capacity_tph, period_production_t=tonnes,
                   period_direct_electricity_mwh=_integral(power[name], weights),
                   utilisation_fraction=tonnes / (capacity_tph * hours) if capacity_tph > 1e-12 else None,
                   utilisation_defined=capacity_tph > 1e-12,
                   period_capacity_cost=float(link.p_nom_opt * link.capital_cost),
                   period_variable_cost=_integral(power[name] * link_cost[name], weights))
        for resource, coefficient, unit in (
            ("H2", "hydrogen_mwh_per_t", "mwh_lhv"),
            ("coal", "coal_mwh_per_t", "mwh_lhv"),
            ("gas", "gas_mwh_per_t", "mwh_lhv"),
            ("ore", "ore_t_per_t", "t"), ("scrap", "scrap_t_per_t", "t"),
        ):
            bus = f"{province} H2" if resource == "H2" else f"{province} steel {resource}"
            row[f"period_{resource.lower()}_{unit}"] = _input_quantity(
                n, name, bus, spec[coefficient], q[name], weights)
        emissions = -solved_output(n, "Link", "p2", [name]).iloc[:, 0]
        if not np.allclose(emissions, q[name] * spec["direct_co2_t_per_t"], atol=1e-6, rtol=1e-7):
            raise ValueError(f"Direct emissions port mismatch: {name}")
        row["period_direct_co2_t"] = _integral(emissions, weights)
        row["period_process_cost"] = row["period_capacity_cost"] + row["period_variable_cost"]
        route_rows.append(row)
    route_frame = pd.DataFrame(route_rows)

    inventory_rows = []
    store_cost = get_as_dense(n, "Store", "marginal_cost")
    for province in industry["annual_demand_t"]:
        name = f"{province} steel inventory"
        store = n.stores.loc[name]
        stock = solved_output(n, "Store", "e", [name]).iloc[:, 0]
        dispatch = solved_output(n, "Store", "p", [name]).iloc[:, 0]
        initial = float(stock.iloc[-1] if store.e_cyclic else store.e_initial)
        inventory_rows.append(dict(common, province=province, component=name,
            capacity_t=float(store.e_nom_opt), capacity_upper_bound_t=float(store.e_nom_max),
            initial_inventory_t=initial, first_interval_end_inventory_t=float(stock.iloc[0]),
            final_inventory_t=float(stock.iloc[-1]), max_inventory_t=float(stock.max()),
            min_inventory_t=float(stock.min()), cyclic=bool(store.e_cyclic),
            period_capacity_cost=float(store.e_nom_opt * store.capital_cost),
            period_variable_cost=_integral(dispatch * store_cost[name], weights)))

    resource_rows = []
    generator_cost = get_as_dense(n, "Generator", "marginal_cost")
    for province in industry["annual_demand_t"]:
        for resource in ("coal", "gas", "ore", "scrap"):
            name = f"{province} steel {resource}"
            if name not in n.generators.index:
                continue
            generator = n.generators.loc[name]
            period_limit = float(generator.e_sum_max)
            dispatch = solved_output(n, "Generator", "p", [name]).iloc[:, 0]
            used = _integral(dispatch, weights)
            unit = "MWh_LHV" if resource in ("coal", "gas") else "t"
            resource_rows.append(dict(common, province=province, resource=resource,
                component=name, unit=unit, annual_limit=period_limit * 8760 / hours,
                annual_limit_method="recovered_from_prorated_period_limit",
                period_limit=period_limit, period_used=used, period_remaining=period_limit - used,
                period_supply_cost=_integral(dispatch * generator_cost[name], weights)))
    resource_columns = list(common) + ["province", "resource", "component", "unit", "annual_limit",
        "annual_limit_method", "period_limit", "period_used", "period_remaining", "period_supply_cost"]

    load_audit = n.meta.get("industry_loads", {})
    has_baseline = bool(load_audit)
    baseline = None
    if has_baseline:
        baseline = pd.DataFrame(load_audit["steel_baseline_mw"],
                                index=pd.DatetimeIndex(load_audit["baseline_snapshots"]))
    load_series = get_as_dense(n, "Load", "p_set")
    total_power = electricity_consumption_by_province(n)
    replacement_rows = []
    for province in industry["annual_demand_t"]:
        fixed_names = n.loads.index[n.loads.bus.eq(province)]
        fixed = _integral(load_series[fixed_names].sum(axis=1), weights)
        names = [r["name"] for r in industry["links"] if r["province"] == province]
        process = _integral(power[names].sum(axis=1), weights)
        gross = _integral(total_power[province], weights)
        original = removed = audited_fixed = None
        if has_baseline:
            original = float(load_audit["original_period_mwh"][province])
            removed = _integral(baseline[province], weights)
            audited_names = [name for name in load_audit["fixed_load_names"]
                             if n.loads.at[name, "bus"] == province]
            audited_fixed = _integral(load_series[audited_names].sum(axis=1), weights)
        replacement_rows.append(dict(common, province=province,
            baseline_status="audited_endogenous_replacement" if has_baseline else "baseline_audit_unavailable",
            original_period_electricity_mwh=original,
            removed_steel_baseline_mwh=removed,
            audited_remaining_fixed_mwh=audited_fixed,
            all_fixed_ac_load_mwh=fixed, endogenous_process_mwh=process,
            process_minus_baseline_mwh=process - removed if has_baseline else None,
            baseline_reconstruction_error_mwh=audited_fixed + removed - original if has_baseline else None,
            gross_ac_withdrawal_mwh=gross,
            other_conversion_withdrawal_mwh=gross - fixed - process))

    tables = {"routes": route_frame, "inventory": pd.DataFrame(inventory_rows),
              "resources": pd.DataFrame(resource_rows, columns=resource_columns),
              "electricity_replacement": pd.DataFrame(replacement_rows)}
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths = {}
    for label, table in tables.items():
        paths[label] = str(output / f"{label}.csv")
        table.to_csv(paths[label], index=False)
    report = dict(common, snapshot_start=str(n.snapshots[0]), snapshot_end=str(n.snapshots[-1]),
        physical_interval_hours=step, accounting=checks, provenance=provenance,
        conventions={
            "quantities": "period totals; never extrapolated to an annual result",
            "capacity": "nominal t/year at each route's capacity_basis_hours; active and new remain separate",
            "utilisation": "period_production_t / (capacity_tpy / capacity_basis_hours * period_hours); blank at zero capacity",
            "inventory": "provincial product pool, not attributed to a route or vintage; initial means pre-first interval",
            "costs": "currency from industry metadata; Link and Store capital_cost already contain period scaling",
            "cost_scope": "route capacity plus Link variable costs only; resource supply costs separate; electricity, upstream H2 and emission-price costs not allocated",
            "hydrogen": "direct process H2 MWh LHV, excluding upstream electricity and costs",
            "baseline": "missing baseline audit produces blank baseline quantities, never inferred zeros",
            "provenance": "taken from this solved network only; manifest checksums verify bytes, not calibration or observation; absent metadata is unknown",
        }, tables={label: {"file": Path(path).name, "rows": len(tables[label])} for label, path in paths.items()})
    paths["audit"] = str(output / "audit.json")
    Path(paths["audit"]).write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return paths


def main():
    import pypsa
    if "snakemake" in globals():
        network = snakemake.input.network
        output_dir = snakemake.output.report_dir
    else:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("network", type=Path)
        parser.add_argument("output_dir", type=Path)
        args = parser.parse_args()
        network, output_dir = args.network, args.output_dir
    paths = export_industry_reports(pypsa.Network(network), output_dir)
    print(json.dumps(paths, indent=2))


if __name__ == "__main__":
    main()
