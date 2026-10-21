"""Integration contracts for sector configuration, baseline replacement and input files."""

from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd
import pypsa
import pytest
import yaml

from add_sectors import add_configured_sectors
from industry_adapter import add_configured_industry, sector_input_paths, sectors_enabled
from industry_model import SteelRoute


def test_example_configuration_is_disabled():
    path = Path(__file__).resolve().parents[1] / "config" / "industry.example.yaml"
    config = yaml.safe_load(path.read_text())
    assert not sectors_enabled(config)
    assert sector_input_paths(config, "derived") == {}


@pytest.fixture
def industry_case(tmp_path):
    full = pd.DataFrame({"Hebei": 100.}, index=pd.date_range("2030-01-01", periods=8760, freq="h"))
    full.iloc[:4, 0] = [100., 200., 300., 400.]
    load_path = tmp_path / "load.h5"
    full.to_hdf(load_path, key="load")
    total = full.Hebei.sum()
    shares = {"agriculture": .05, "industry": .55, "construction": .05,
              "services": .1, "residential": .15, "steel": .2, "other_ferrous": .1}
    annual = pd.DataFrame([{"year": 2030, "province": "Hebei", "sector": sector,
                            "value": total * share, "unit": "MWh"} for sector, share in shares.items()])
    annual_path = tmp_path / "sectors.csv"
    annual.to_csv(annual_path, index=False)
    config = {"sectors": {"electric_vehicles": {"enabled": False}, "industry": {
        "mode": "fixed_load", "annual_sector_demand": str(annual_path),
        "steel": {"currency": "synthetic_test_currency", "inventory_annual_cost_per_t": 0.}}}}
    steel = config["sectors"]["industry"]["steel"]
    quantities = {
        "annual_demand": pd.DataFrame([{"year": 2030, "province": "Hebei", "value": 8760., "unit": "t"}]),
        "inventory": pd.DataFrame([{"year": 2030, "province": "Hebei", "value": 2., "unit": "t"}]),
        "capacities": pd.DataFrame([{"year": 2030, "province": "Hebei", "route": "test_route",
                                     "existing_tpy": 8760., "new_max_tpy": 8760., "unit": "t/year"}]),
        "resources": pd.DataFrame([{"year": 2030, "province": "Hebei", "resource": "scrap",
                                    "annual_limit": 8760., "marginal_cost": 1., "unit": "t",
                                    "currency": "synthetic_test_currency"}]),
    }
    paths = {"elec_load": str(load_path), "industry_sector_demand": str(annual_path)}
    for name, table in quantities.items():
        path = tmp_path / f"{name}.csv"
        table.to_csv(path, index=False)
        steel[name] = str(path)
        paths[f"industry_{name}"] = str(path)
    # Synthetic conservation fixture, not a recommended scientific route.
    route = SteelRoute("test_route", .5, 0., 0., 0., 0., 1., .1, 1., .1, 0.,
                       minimum_load=.1, ramp_up_per_hour=.5, ramp_down_per_hour=.5)
    route_path = tmp_path / "routes.yaml"
    route_path.write_text(yaml.safe_dump({"year": 2030, "currency": "synthetic_test_currency", "routes": [asdict(route)]}))
    steel["routes"] = str(route_path)
    paths["industry_routes"] = str(route_path)
    n = pypsa.Network()
    n.set_snapshots(full.index[:4])
    n.add("Carrier", "AC")
    n.add("Carrier", "heat")
    n.add("Bus", "Hebei", carrier="AC")
    n.add("Bus", "Hebei heat", carrier="heat")
    n.add("Load", "Hebei", bus="Hebei", p_set=full.Hebei.iloc[:4])
    n.add("Load", "existing heat", bus="Hebei heat", p_set=10.)
    return n, config, paths, full


@pytest.mark.parametrize("ev,mode,enabled", [
    (False, "off", False), (True, "off", True), (False, "fixed_load", True),
    (False, "endogenous", True), (True, "endogenous", True),
])
def test_sector_enablement_is_not_dict_truthiness(industry_case, ev, mode, enabled):
    _, config, _, _ = industry_case
    config["sectors"]["electric_vehicles"]["enabled"] = ev
    config["sectors"]["industry"]["mode"] = mode
    assert sectors_enabled(config) is enabled


def test_only_enabled_sectors_declare_files(industry_case):
    _, config, _, _ = industry_case
    paths = sector_input_paths(config, "derived")
    assert set(paths) == {"elec_load", "industry_sector_demand"}
    ev = config["sectors"]["electric_vehicles"]
    ev.update(enabled=True, transport={"passenger_bev": {"enable": True}, "freight_bev": {"enable": False}})
    paths = sector_input_paths(config, "derived")
    assert "transport_demand_passenger" in paths
    assert "transport_demand_freight" not in paths
    config["sectors"]["industry"]["mode"] = "off"
    assert set(sector_input_paths(config, "derived")) == {"transport_demand_passenger"}
    ev["enabled"] = False
    assert sector_input_paths(config, "derived") == {}


def test_carbon_reduction_dependency_only_when_needed(industry_case):
    _, config, _, _ = industry_case
    config["sectors"]["industry"]["mode"] = "endogenous"
    config["co2_scenarios"] = {"test": {"control": "price"}}
    assert "industry_carbon_baseline" not in sector_input_paths(config, "derived")
    config["co2_scenarios"]["test"]["control"] = "budget_from_reduction"
    with pytest.raises(ValueError, match="carbon_baseline"):
        sector_input_paths(config, "derived")
    config["sectors"]["industry"]["carbon_baseline"] = "processed/baseline.csv"
    assert sector_input_paths(config, "derived")["industry_carbon_baseline"] == "processed/baseline.csv"


def test_off_never_opens_industry_files(industry_case):
    n, config, _, _ = industry_case
    config["sectors"]["industry"]["mode"] = "off"
    result = add_configured_sectors(n, config, planning_year=2030, inputs={})
    assert result is n
    assert set(n.loads.index) == {"Hebei", "existing heat"}


def test_fixed_load_preserves_ac_and_other_loads_and_serializes_audit(industry_case, tmp_path):
    n, config, paths, full = industry_case
    result = add_configured_industry(n, config, planning_year=2030, inputs=paths)
    assert "Hebei" not in result.loads.index
    assert "existing heat" in result.loads.index
    assert "Hebei" in n.loads.index  # input network is unchanged
    selected = result.loads.index[result.loads.bus == "Hebei"]
    np.testing.assert_allclose(result.loads_t.p_set[selected].sum(axis=1), full.Hebei.iloc[:4])
    audit = result.meta["industry_loads"]
    assert audit["annual_total_mwh"]["Hebei"] == full.Hebei.sum()
    assert audit["original_period_mwh"]["Hebei"] == 1000.
    assert audit["removed_steel_period_mwh"]["Hebei"] == 0.
    assert audit["steel_baseline_mw"]["Hebei"] == [20., 40., 60., 80.]
    assert audit["reconstruction_max_abs_mw"] < 1e-9
    assert len(audit["sources"]["elec_load"]["sha256"]) == 64
    path = tmp_path / "sector_network.nc"
    result.export_to_netcdf(path)
    restored = pypsa.Network(path)
    assert restored.meta["industry_loads"] == audit


def test_endogenous_process_replaces_only_baseline_steel(industry_case):
    n, config, paths, full = industry_case
    config["sectors"]["industry"]["mode"] = "endogenous"
    result = add_configured_sectors(n, config, planning_year=2030, inputs=paths)
    assert "Hebei electricity steel" not in result.loads.index
    assert "Hebei electricity other_ferrous" in result.loads.index
    assert "Hebei steel demand" in result.loads.index
    assert "Hebei steel test_route new" in result.links.index
    selected = result.loads.index[result.loads.bus == "Hebei"]
    np.testing.assert_allclose(result.loads_t.p_set[selected].sum(axis=1), full.Hebei.iloc[:4] * .8)
    assert result.meta["industry_loads"]["removed_steel_period_mwh"]["Hebei"] == 200.
    assert result.meta["industry"]["annual_demand_t"]["Hebei"] == 8760.
    assert result.meta["industry"]["period_hours"] == 4.


@pytest.mark.parametrize("mode", ["off", "fixed_load", "endogenous"])
def test_ev_and_industry_combinations_preserve_ev_semantics(industry_case, tmp_path, mode):
    n, config, paths, full = industry_case
    config["sectors"]["industry"]["mode"] = mode
    config["sectors"]["electric_vehicles"] = {"enabled": True, "transport": {
        "passenger_bev": {"enable": True, "annual_consumption": 3., "charge_rate": .01, "share_charger": .8},
        "freight_bev": {"enable": False},
    }}
    charging = pd.DataFrame({"Hebei": 1.}, index=full.index)
    path = tmp_path / "charging.csv"
    charging.to_csv(path)
    paths["transport_demand_passenger"] = str(path)
    result = add_configured_sectors(n, config, planning_year=2030, inputs=paths)
    assert "Hebei EV_passenger_load" in result.loads.index
    assert "Hebei EV_freight_load" not in result.loads.index
    assert result.links.at["Hebei EV_passenger_charger", "p_nom"] == pytest.approx(8760 / 3 * .01 * .8)
    np.testing.assert_allclose(result.loads_t.p_set["Hebei EV_passenger_load"], 1.)


def test_baseline_mismatch_refuses_to_remove_anything(industry_case):
    n, config, paths, _ = industry_case
    n.loads_t.p_set.loc[n.snapshots[0], "Hebei"] += 1.
    before = n.loads.copy(deep=True)
    with pytest.raises(ValueError, match="differs from the annual HDF"):
        add_configured_industry(n, config, planning_year=2030, inputs=paths)
    pd.testing.assert_frame_equal(n.loads, before)


def test_short_hdf_is_not_mistaken_for_full_annual_demand(industry_case):
    n, config, paths, full = industry_case
    full.iloc[:4].to_hdf(paths["elec_load"], key="load", mode="w")
    with pytest.raises(ValueError, match="full annual"):
        add_configured_industry(n, config, planning_year=2030, inputs=paths)
    assert "Hebei" in n.loads.index


def test_optional_full_year_hdf_weights(industry_case):
    n, config, paths, full = industry_case
    pd.DataFrame({"generators": 1.}, index=full.index).to_hdf(paths["elec_load"], key="weights")
    result = add_configured_industry(n, config, planning_year=2030, inputs=paths)
    assert result.meta["industry_loads"]["annual_total_mwh"]["Hebei"] == full.Hebei.sum()


@pytest.mark.parametrize("field,value,error", [
    ("currency", None, "currency"),
    ("inventory_annual_cost_per_t", None, "inventory_annual_cost"),
])
def test_missing_scientific_configuration_does_not_get_defaults(industry_case, field, value, error):
    n, config, paths, _ = industry_case
    config["sectors"]["industry"]["mode"] = "endogenous"
    config["sectors"]["industry"]["steel"][field] = value
    with pytest.raises(ValueError, match=error):
        add_configured_industry(n, config, planning_year=2030, inputs=paths)
    assert "Hebei" in n.loads.index


def test_route_flexibility_must_be_explicit(industry_case):
    n, config, paths, _ = industry_case
    config["sectors"]["industry"]["mode"] = "endogenous"
    with open(paths["industry_routes"]) as stream:
        data = yaml.safe_load(stream)
    del data["routes"][0]["minimum_load"]
    with open(paths["industry_routes"], "w") as stream:
        yaml.safe_dump(data, stream)
    with pytest.raises(ValueError, match="all SteelRoute parameters"):
        add_configured_industry(n, config, planning_year=2030, inputs=paths)


def test_repeated_attachment_cannot_subtract_twice(industry_case):
    n, config, paths, _ = industry_case
    result = add_configured_industry(n, config, planning_year=2030, inputs=paths)
    with pytest.raises(ValueError, match="already been attached"):
        add_configured_industry(result, config, planning_year=2030, inputs=paths)
