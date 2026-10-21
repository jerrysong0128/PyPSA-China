"""Analytic LP checks, deliberately synthetic rather than scientific inputs."""

import numpy as np
import pandas as pd
import pypsa
import pytest

from industry_model import (
    SteelRoute, add_industry_constraints, add_steel_industry,
    chronological_hours, steel_dispatch,
)


def network(hours=2, step=3, power_cost=1, power_carbon=1):
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=hours, freq=f"{step}h"))
    n.snapshot_weightings[:] = step
    n.add("Carrier", "AC")
    n.add("Carrier", "power", co2_emissions=power_carbon)
    n.add("Bus", "Anhui", carrier="AC")
    n.add("Generator", "grid", bus="Anhui", carrier="power", p_nom=100,
          marginal_cost=power_cost, efficiency=1)
    return n


def route(name="BF-BOF", **kwargs):
    defaults = dict(name=name, electricity_mwh_per_t=0.5, hydrogen_mwh_per_t=0,
                    coal_mwh_per_t=0, gas_mwh_per_t=0, ore_t_per_t=0,
                    scrap_t_per_t=0, direct_co2_t_per_t=2,
                    new_annual_cost_per_tpy=1, active_annual_cost_per_tpy=0.1,
                    variable_cost_per_t=0)
    defaults.update(kwargs)
    return SteelRoute(**defaults)


def attach(n, routes=None, inventory=0, resources=None, capacity=4 * 8760):
    routes = routes or [route()]
    caps = pd.DataFrame([dict(province="Anhui", route=r.name, existing_tpy=capacity,
                              new_max_tpy=capacity) for r in routes])
    if resources is None:
        resources = pd.DataFrame(columns=["province", "resource", "annual_limit", "marginal_cost"])
    add_steel_industry(n, pd.Series({"Anhui": 2 * 8760}), caps, routes, resources,
                       inventory_t=pd.Series({"Anhui": inventory}), currency="EUR2020")
    return n


def solve(n):
    return n.optimize(solver_name="highs", extra_functionality=add_industry_constraints,
                      log_to_console=False)


def test_weighted_material_energy_and_carbon():
    n = attach(network())
    n.add("GlobalConstraint", "joint-carbon", type="primary_energy",
          carrier_attribute="co2_emissions", sense="<=", constant=30)
    assert solve(n) == ("ok", "optimal")
    production, power = steel_dispatch(n)
    assert production.sum(axis=1).to_numpy() == pytest.approx([2, 2])
    assert (power.sum(axis=1) * n.snapshot_weightings.generators).sum() == pytest.approx(6)
    assert (n.generators_t.p["Anhui steel emissions"] * 3).sum() == pytest.approx(24)
    assert (n.generators_t.p["grid"] * 3).sum() == pytest.approx(6)
    assert n.stores_t.e["Anhui steel inventory"].abs().max() < 1e-7
    # Annual active cost 0.1 per tpy prorated to six hours: 1.2 + power cost 6.
    assert n.objective == pytest.approx(7.2)
    n.global_constraints.at["joint-carbon", "constant"] = 29.9
    assert solve(n)[1] == "infeasible"


def test_binding_carbon_cap_changes_route_and_objective():
    routes = [route("dirty", direct_co2_t_per_t=2),
              route("clean", direct_co2_t_per_t=0, variable_cost_per_t=10)]
    n = attach(network(power_carbon=0), routes=routes)
    n.add("GlobalConstraint", "joint-carbon", type="primary_energy",
          carrier_attribute="co2_emissions", sense="<=", constant=12)
    assert solve(n) == ("ok", "optimal")
    before = n.objective
    assert abs(n.global_constraints.at["joint-carbon", "mu"]) > 1
    assert (n.generators_t.p["Anhui steel emissions"] * 3).sum() == pytest.approx(12)
    n.global_constraints.at["joint-carbon", "constant"] = 10.8
    assert solve(n) == ("ok", "optimal")
    assert n.objective - before == pytest.approx(6)


def test_bounded_inventory_shifts_production_and_conserves_mass():
    n = attach(network(hours=4, step=1, power_carbon=0), inventory=4)
    n.generators_t.marginal_cost["grid"] = [1, 1, 100, 100]
    assert solve(n) == ("ok", "optimal")
    production, _ = steel_dispatch(n)
    q = production.sum(axis=1)
    inventory = n.stores_t.e["Anhui steel inventory"]
    assert q.sum() == pytest.approx(8)
    assert q.iloc[:2].sum() == pytest.approx(8)
    assert inventory.max() == pytest.approx(4)
    previous = np.roll(inventory.to_numpy(), 1)
    assert inventory.to_numpy() - previous == pytest.approx(q.to_numpy() - 2)


def test_scrap_limit_and_port_balance():
    resources = pd.DataFrame([dict(province="Anhui", resource="scrap",
                                    annual_limit=8760, marginal_cost=1)])
    routes = [route("BF-BOF", variable_cost_per_t=5),
              route("scrap-EAF", scrap_t_per_t=1.1, direct_co2_t_per_t=0)]
    n = attach(network(), routes=routes, resources=resources)
    assert solve(n) == ("ok", "optimal")
    scrap = (n.generators_t.p["Anhui steel scrap"] * 3).sum()
    q, _ = steel_dispatch(n)
    scrap_steel = (q.filter(like="scrap-EAF").sum(axis=1) * 3).sum()
    assert scrap == pytest.approx(6)
    assert scrap_steel * 1.1 == pytest.approx(scrap)


def test_hydrogen_consumption_is_separate_from_direct_power():
    n = network(power_carbon=0)
    n.add("Carrier", "H2")
    n.add("Bus", "Anhui H2", carrier="H2")
    n.add("Link", "electrolyser", bus0="Anhui", bus1="Anhui H2", p_nom=100,
          efficiency=0.5)
    attach(n, routes=[route("H2-DRI-EAF", hydrogen_mwh_per_t=1)])
    assert solve(n) == ("ok", "optimal")
    assert n.generators_t.p["grid"].to_numpy() == pytest.approx([5, 5])
    assert n.links_t.p0["electrolyser"].to_numpy() == pytest.approx([4, 4])


def test_cyclic_ramps_constrain_both_directions_and_survive_export(tmp_path):
    n = attach(network(hours=4, step=1), routes=[route(ramp_up_per_hour=0.1,
                                                    ramp_down_per_hour=0.1)], inventory=4)
    n.generators_t.marginal_cost["grid"] = [1, 30, 80, 100]
    path = tmp_path / "steel.nc"
    n.export_to_netcdf(path)
    n = pypsa.Network(path)
    assert solve(n) == ("ok", "optimal")
    assert "industry-cyclic-ramp-up-0" in n.model.constraints
    for r in n.meta["industry"]["links"]:
        p = n.links_t.p0[r["name"]].to_numpy()
        bound = n.links.at[r["name"], "p_nom_opt"] * 0.1
        assert (np.abs(p - np.roll(p, 1)) <= bound + 1e-6).all()


def test_fail_closed_on_temporal_and_parameter_errors():
    n = network()
    n.snapshot_weightings.stores = 1
    with pytest.raises(ValueError, match="stores weights"):
        chronological_hours(n)
    with pytest.raises(ValueError, match="positive"):
        route(electricity_mwh_per_t=0).validate()
    with pytest.raises(ValueError, match="Missing bounded scrap"):
        attach(network(), routes=[route(scrap_t_per_t=1)])
    with pytest.raises(ValueError, match="Missing upstream H2"):
        attach(network(), routes=[route(hydrogen_mwh_per_t=1)])
