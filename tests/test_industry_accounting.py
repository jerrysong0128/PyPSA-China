import pandas as pd
import pytest

from industry_accounting import (
    electricity_consumption_by_province, primary_energy_emissions,
    steel_baseline_emissions, validate_industry_solution,
)
from industry_model import add_industry_constraints
from solve_network import add_emission_prices, add_operational_reserve_margin
from tests.test_industry_model import attach, network, solve


def test_joint_reduction_baseline_and_disabled_compatibility(tmp_path):
    from _helpers import GHGConfigHandler
    from constants import PROV_NAMES, CO2_EL_2020, CO2_BASEYEAR_EM
    path = tmp_path / "baseline.csv"
    pd.DataFrame([dict(province=p, year=2020, route="test", production_t=10,
                       direct_co2_t_per_t=2, source_id="synthetic", method="test")
                  for p in PROV_NAMES]).to_csv(path, index=False)
    config = {"scenario": {"co2_pathway": ["test"], "planning_horizons": [2030]},
              "co2_scenarios": {"test": {"control": "reduction", "pathway": {2030: 0.4}}},
              "sectors": {"industry": {"mode": "endogenous", "carbon_baseline": str(path)}}}
    for heat, energy_base in ((False, CO2_EL_2020), (True, CO2_BASEYEAR_EM)):
        config["heat_coupling"] = heat
        out = GHGConfigHandler(config).handle_ghg_scenarios()
        assert out["co2_scenarios"]["test"]["pathway"][2030] == pytest.approx((energy_base + 20 * len(PROV_NAMES)) * 0.6)
    config["sectors"]["industry"] = {"mode": "off"}
    out = GHGConfigHandler(config).handle_ghg_scenarios()
    assert out["co2_scenarios"]["test"]["pathway"][2030] == pytest.approx(CO2_BASEYEAR_EM * 0.6)


def test_emission_price_and_validation():
    n = attach(network())
    add_emission_prices(n, {"co2": 10})
    assert solve(n) == ("ok", "optimal")
    report = validate_industry_solution(n)
    assert report["steel_direct_co2_t"] == pytest.approx(24)
    assert report["total_co2_t"] == pytest.approx(30)
    assert not report["annual_result"]
    assert n.objective == pytest.approx(7.2 + 30 * 10)
    assert electricity_consumption_by_province(n)["Anhui"].to_numpy() == pytest.approx([1, 1])
    n.generators_t.p["Anhui steel emissions"] += 1
    with pytest.raises(ValueError, match="physical checks"):
        validate_industry_solution(n)


def test_inventory_cost_affects_capacity_decision():
    n = attach(network(hours=4, step=1), inventory=4)
    n.generators_t.marginal_cost["grid"] = [1, 1, 100, 100]
    # Already period-scaled: each tonne of storage costs 1000 in this solve.
    n.stores.loc[:, "capital_cost"] = 1000
    assert solve(n) == ("ok", "optimal")
    assert n.stores.e_nom_opt.sum() == pytest.approx(0)
    validate_industry_solution(n)


def test_solved_report_reconciles_replaced_baseline():
    n = attach(network())
    n.add("Load", "fixed sector", bus="Anhui", p_set=3)
    n.meta["industry_loads"] = {"mode": "endogenous", "fixed_load_names": ["fixed sector"],
                                "baseline_snapshots": [t.isoformat() for t in n.snapshots],
                                "steel_baseline_mw": {"Anhui": [1, 1]},
                                "original_period_mwh": {"Anhui": 24}}
    assert solve(n) == ("ok", "optimal")
    report = validate_industry_solution(n)
    assert report["electricity_replacement"]["removed_baseline_mwh"] == 6
    assert report["electricity_replacement"]["endogenous_process_mwh"] == pytest.approx(6)
    assert report["electricity_replacement"]["gross_ac_withdrawal_mwh"] == pytest.approx(24)
    n.loads.at["fixed sector", "p_set"] = 4
    with pytest.raises(ValueError, match="baseline_replacement_fraction"):
        validate_industry_solution(n)


def test_reserve_uses_mw_not_product_tonnes():
    n = attach(network(power_carbon=0))
    n.add("Load", "fixed power", bus="Anhui", p_set=3)
    n.generators.at["grid", "p_nom"] = 4.4
    config = {"operational_reserve": {"epsilon_load": 0.1, "epsilon_vres": 0,
                                      "contingency": 0}, "Techs": {"non_dispatchable": []}}

    def callback(n, snapshots):
        add_industry_constraints(n, snapshots)
        add_operational_reserve_margin(n, config)

    assert n.optimize(solver_name="highs", extra_functionality=callback,
                      log_to_console=False) == ("ok", "optimal")
    # 3 MW fixed + 1 MW steel -> 0.4 MW reserves, not 0.5 from adding 2 t/h.
    reserve = n.model["Generator-r"].solution.to_pandas()["grid"]
    assert reserve.to_numpy() == pytest.approx([0.4, 0.4])


def test_carbon_baseline_requires_production_evidence(tmp_path):
    path = tmp_path / "baseline.csv"
    frame = pd.DataFrame([dict(province="Anhui", year=2020, route="BF-BOF",
                                production_t=10, direct_co2_t_per_t=2,
                                source_id="synthetic-test", method="test fixture")])
    frame.to_csv(path, index=False)
    assert steel_baseline_emissions(path, ["Anhui"]) == 20
    with pytest.raises(ValueError, match="every model province"):
        steel_baseline_emissions(path, ["Anhui", "Jiangsu"])
    frame.year = 2026
    frame.to_csv(path, index=False)
    with pytest.raises(ValueError, match="2020 production"):
        steel_baseline_emissions(path, ["Anhui"])


def test_primary_energy_includes_noncyclic_stock_depletion():
    n = attach(network())
    assert solve(n) == ("ok", "optimal")
    n.add("Carrier", "carbon stock", co2_emissions=2)
    n.add("Bus", "stock bus", carrier="carbon stock")
    n.add("Store", "stock", bus="stock bus", carrier="carbon stock", e_nom=5, e_initial=5)
    n.stores_t.e["stock"] = [4, 3]
    assert primary_energy_emissions(n)[0] == pytest.approx(34)
