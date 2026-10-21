#!/usr/bin/env python3
"""One-province, 8760-hour synthetic technical benchmark; not empirical evidence.

All prices, capacities, process parameters and 30-day inventory are deliberately
synthetic. This exercises the production/accounting core without provincial data
or the full PIK network. It cannot validate real steel operating flexibility.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import gc
import json
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd
import pypsa

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "workflow/scripts"))
from industry_model import (SteelRoute, add_industry_constraints, add_steel_industry,
                            steel_dispatch)
from industry_accounting import validate_industry_solution, electricity_consumption_by_province

PROVINCE = "Anhui"
DEMAND = 87600.0
CARBON_CAP = 35000.0
TOLERANCE = 1e-5


def build_network(inventory_days):
    n = pypsa.Network()
    snapshots = pd.date_range("2030-01-01", periods=8760, freq="h")
    n.set_snapshots(snapshots)
    n.snapshot_weightings.loc[:, :] = 1.0
    phase = 2 * np.pi * np.arange(8760) / 8760
    # Low prices and high renewable availability around January; the reverse
    # around July. All 8760 consecutive physical hours are retained.
    price = pd.Series(110 - 70 * np.cos(phase), index=snapshots)
    renewable = pd.Series(0.55 + 0.35 * np.cos(phase), index=snapshots)
    for carrier, emissions in [("AC", 0.0), ("synthetic grid", 0.35),
                                ("synthetic renewable", 0.0)]:
        n.add("Carrier", carrier, co2_emissions=emissions)
    n.add("Bus", PROVINCE, carrier="AC")
    n.add("Load", "nonsteel electricity", bus=PROVINCE, p_set=5.0)
    n.add("Generator", "grid", bus=PROVINCE, carrier="synthetic grid",
          p_nom=30.0, marginal_cost=price, efficiency=1.0)
    n.add("Generator", "renewable", bus=PROVINCE,
          carrier="synthetic renewable", p_nom=10.0, p_max_pu=renewable,
          marginal_cost=0.0)
    route = SteelRoute(
        name="synthetic-EAF", electricity_mwh_per_t=0.8,
        hydrogen_mwh_per_t=0.0, coal_mwh_per_t=0.0, gas_mwh_per_t=0.0,
        ore_t_per_t=0.0, scrap_t_per_t=1.1, direct_co2_t_per_t=0.1,
        new_annual_cost_per_tpy=4.0, active_annual_cost_per_tpy=0.5,
        variable_cost_per_t=2.0, minimum_load=0.2,
        ramp_up_per_hour=0.1, ramp_down_per_hour=0.1,
    )
    capacities = pd.DataFrame([dict(province=PROVINCE, route=route.name,
                                    existing_tpy=70080.0, new_max_tpy=175200.0)])
    resources = pd.DataFrame([dict(province=PROVINCE, resource="scrap",
                                   annual_limit=105120.0, marginal_cost=20.0)])
    inventory_limit = DEMAND / 365 * inventory_days
    add_steel_industry(n, pd.Series({PROVINCE: DEMAND}), capacities, [route],
                       resources, currency="synthetic_currency_units",
                       inventory_t=pd.Series({PROVINCE: inventory_limit}),
                       inventory_annual_cost_per_t=1.0)
    n.add("GlobalConstraint", "joint-carbon", type="primary_energy",
          carrier_attribute="co2_emissions", sense="<=", constant=CARBON_CAP)
    return n, price, renewable, route


def constraints(n, snapshots):
    add_industry_constraints(n, snapshots)
    # Native cyclic storage closes the year. Setting the final stock to zero
    # also makes the pre-first-hour stock exactly zero: no free initial steel.
    stock = n.model["Store-e"].sel(Store=f"{PROVINCE} steel inventory")
    n.model.add_constraints(stock.isel(snapshot=-1) == 0,
                            name="benchmark-zero-boundary-stock")


def run_case(days, output, solver):
    n, price, renewable, route = build_network(days)
    started = time.perf_counter()
    options = dict(threads=2)
    if solver == "highs":
        options.update(solver="ipm", run_crossover="on")
    status, condition = n.optimize(solver_name=solver, solver_options=options,
                                   extra_functionality=constraints,
                                   log_to_console=False)
    seconds = time.perf_counter() - started
    if (status, condition) != ("ok", "optimal"):
        raise RuntimeError(f"{days}-day case failed: {status}, {condition}")
    checks = validate_industry_solution(n, tolerance=TOLERANCE)
    q, direct_power = steel_dispatch(n)
    production = q.sum(axis=1)
    electricity = direct_power.sum(axis=1)
    stock = n.stores_t.e[f"{PROVINCE} steel inventory"]
    inventory_opt = float(n.stores.at[f"{PROVINCE} steel inventory", "e_nom_opt"])
    expected_power = 43800 + DEMAND * route.electricity_mwh_per_t
    accounted_power = float(electricity_consumption_by_province(n)[PROVINCE].sum())
    demand_residual = abs(float(production.sum()) - DEMAND)
    boundary_residual = abs(float(stock.iloc[-1]))
    initial_balance_residual = abs(float(stock.iloc[0]) - (float(production.iloc[0]) - DEMAND / 8760))
    power_residual = abs(accounted_power - expected_power)
    co2_expected = float(n.generators_t.p.grid.sum() * 0.35 + DEMAND * 0.1)
    co2_residual = abs(checks["total_co2_t"] - co2_expected)
    for name, residual in dict(demand=demand_residual, boundary=boundary_residual,
                               initial_balance=initial_balance_residual,
                               electricity=power_residual, carbon=co2_residual).items():
        if residual > TOLERANCE:
            raise AssertionError(f"{days}-day {name} residual: {residual}")
    costs = {
        "grid_energy": float((n.generators_t.p.grid * price).sum()),
        "scrap": float(n.generators_t.p[f"{PROVINCE} steel scrap"].sum() * 20),
        "route_variable": float(production.sum() * route.variable_cost_per_t),
        "route_capacity": float((n.links.p_nom_opt * n.links.capital_cost).sum()),
        "inventory_capacity": inventory_opt,
    }
    objective_residual = abs(sum(costs.values()) - float(n.objective))
    if objective_residual > 1e-3:
        raise AssertionError(f"Objective cost reconciliation: {objective_residual}")
    hourly = pd.DataFrame({
        "price_per_mwh": price, "renewable_availability_pu": renewable,
        "steel_production_t": production, "steel_demand_t": DEMAND / 8760,
        "steel_direct_electricity_mwh": electricity, "steel_inventory_t": stock,
        "grid_mwh": n.generators_t.p.grid,
        "renewable_mwh": n.generators_t.p.renewable,
        "direct_steel_co2_t": n.generators_t.p[f"{PROVINCE} steel emissions"],
    })
    case_name = "no_inventory" if days == 0 else "synthetic_30_day_inventory"
    hourly.to_csv(output / f"{case_name}_hourly.csv", index_label="snapshot")
    monthly = hourly.resample("MS").sum()
    monthly["mean_price_per_mwh"] = price.resample("MS").mean()
    monthly["max_inventory_t"] = stock.resample("MS").max()
    monthly = monthly.drop(columns=["price_per_mwh", "renewable_availability_pu", "steel_inventory_t"])
    monthly.to_csv(output / f"{case_name}_monthly.csv", index_label="month")
    low = price <= price.quantile(0.25)
    high = price >= price.quantile(0.75)
    result = dict(
        case=case_name, status=status, condition=condition, solver=solver,
        solve_seconds=seconds, hours=len(n.snapshots), objective=float(n.objective),
        cost_components=costs, objective_reconciliation_error=objective_residual,
        annual_demand_t=DEMAND, annual_production_t=float(production.sum()),
        direct_electricity_mwh=float(electricity.sum()), total_electricity_mwh=accounted_power,
        low_price_quartile_steel_t=float(production[low].sum()),
        high_price_quartile_steel_t=float(production[high].sum()),
        low_price_quartile_direct_electricity_mwh=float(electricity[low].sum()),
        high_price_quartile_direct_electricity_mwh=float(electricity[high].sum()),
        grid_mwh=float(n.generators_t.p.grid.sum()),
        renewable_mwh=float(n.generators_t.p.renewable.sum()),
        inventory_limit_t=DEMAND / 365 * days, inventory_capacity_t=inventory_opt,
        inventory_min_t=float(stock.min()), inventory_max_t=float(stock.max()),
        pre_first_hour_inventory_t=0.0, final_inventory_t=float(stock.iloc[-1]),
        annual_demand_error_t=demand_residual, initial_balance_error_t=initial_balance_residual,
        electricity_error_mwh=power_residual, co2_error_t=co2_residual,
        carbon_limit_t=CARBON_CAP, route_parameters=asdict(route), accounting=checks,
    )
    del n
    gc.collect()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--solver", choices=["highs", "gurobi"], default="highs")
    parser.add_argument("--output", type=Path, default=ROOT / "results/industry_seasonal_benchmark")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    baseline = run_case(0, args.output, args.solver)
    storage = run_case(30, args.output, args.solver)
    comparison = dict(
        cost_reduction=baseline["objective"] - storage["objective"],
        cost_reduction_fraction=1 - storage["objective"] / baseline["objective"],
        low_price_quartile_production_increase_t=storage["low_price_quartile_steel_t"] - baseline["low_price_quartile_steel_t"],
        high_price_quartile_production_reduction_t=baseline["high_price_quartile_steel_t"] - storage["high_price_quartile_steel_t"],
        annual_direct_electricity_change_mwh=storage["direct_electricity_mwh"] - baseline["direct_electricity_mwh"],
        total_co2_change_t=storage["accounting"]["total_co2_t"] - baseline["accounting"]["total_co2_t"],
    )
    if comparison["cost_reduction"] <= 0 or comparison["low_price_quartile_production_increase_t"] <= 0 or comparison["high_price_quartile_production_reduction_t"] <= 0:
        raise AssertionError("Expected seasonal shift and cost reduction were not demonstrated")
    result = dict(purpose="synthetic_technical_validation_only",
        warning="30-day inventory and all parameters are synthetic; no recommendation for empirical steel inventory or flexibility",
        chronology="8760 consecutive physical hourly snapshots in 2030; all weights1; zero initial and terminal steel",
        comparisons=comparison, cases=[baseline, storage])
    (args.output / "summary.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps(comparison, indent=2))


if __name__ == "__main__":
    main()
