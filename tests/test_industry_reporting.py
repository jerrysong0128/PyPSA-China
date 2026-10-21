"""Report-unit regressions using analytically specified solved dispatch."""

import pandas as pd
import pypsa
import pytest
from pypsa.descriptors import get_switchable_as_dense

from constants import PLOT_CAP_UNITS
from make_summary import (
    calculate_capacities, calculate_expanded_capacities, calculate_metrics,
    calculate_peak_dispatch, calculate_supply_energy, calculate_weighted_prices,
)
from plot_statistics import prepare_province_peakload_capacity_data


def reporting_network(industry=True):
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=2, freq="h"))
    n.snapshot_weightings.loc[:, :] = [[1, 1, 1], [3, 3, 3]]
    for carrier in ["AC", "grid", "electricity", "transmission", "H2", "electrolysis", "steel", "steel route", "heat"]:
        n.add("Carrier", carrier, nice_name=carrier, color="grey")
    for bus, location in [("A", "Anhui"), ("A2", "Anhui"), ("B", "Jiangsu")]:
        n.add("Bus", bus, carrier="AC", location=location)
        n.add("Generator", bus + " grid", bus=bus, carrier="grid", p_nom=100)
    for name, bus, power in [("A fixed", "A", [1, 3]), ("A static", "A2", 2), ("B fixed", "B", [6, 1])]:
        n.add("Load", name, bus=bus, carrier="electricity", p_set=power)
    n.add("Link", "transmission", bus0="A", bus1="B", carrier="transmission", p_nom=100, p_min_pu=-1)
    n.links_t.p0["transmission"] = [2, -1]
    n.links_t.p1["transmission"] = [-2, 1]
    n.generators_t.p["A grid"] = [3, 2]
    n.generators_t.p["A2 grid"] = [2, 2]
    n.generators_t.p["B grid"] = [4, 2]
    if industry:
        n.add("Bus", "H2", carrier="H2", unit="MWh", location="Anhui")
        n.add("Bus", "steel", carrier="steel", unit="t", location="Anhui")
        n.add("Bus", "heat", carrier="heat", unit="MWh", location="Anhui")
        n.add("Load", "hydrogen demand", bus="H2", carrier="H2", p_set=[2, 1])
        n.add("Load", "steel demand", bus="steel", carrier="steel", p_set=[1000, 2000])
        n.add("Load", "heat demand", bus="heat", carrier="heat", p_set=10000)
        n.add("Link", "electrolyser", bus0="A", bus1="H2", carrier="electrolysis", efficiency=0.5, p_nom=10)
        n.add("Link", "steel process", bus0="A", bus1="steel", carrier="steel route", efficiency=1000, p_nom=10)
        n.add("Generator", "heat source", bus="heat", carrier="heat", p_nom=10000)
        n.add("Store", "steel inventory", bus="steel", carrier="steel", e_nom=1000000)
        n.stores["e_nom_opt"] = n.stores.e_nom
        n.stores_t.p["steel inventory"] = 0
        n.stores_t.e["steel inventory"] = 0
        n.links_t.p0["electrolyser"] = [4, 2]
        n.links_t.p1["electrolyser"] = [-2, -1]
        n.links_t.p0["steel process"] = [1, 2]
        n.links_t.p1["steel process"] = [-1000, -2000]
        n.generators_t.p["A grid"] = [8, 6]
        n.generators_t.p["heat source"] = 10000
    n.loads_t.p = get_switchable_as_dense(n, "Load", "p_set")
    n.links["p_nom_opt"] = n.links.p_nom
    n.generators["p_nom_opt"] = n.generators.p_nom
    for bus, price in {"A": [10, 20], "A2": [10, 20], "B": [30, 40]}.items():
        n.buses_t.marginal_price[bus] = price
    for bus in n.buses.index.difference(["A", "A2", "B"]):
        n.buses_t.marginal_price[bus] = 1
    # This fixture supplies analytic dispatch rather than running an optimizer.
    # Every model cost is zero, so its matching stored objective is exactly zero.
    n._objective = 0.0
    return n


def test_electricity_peak_includes_processes_excludes_tonnes_heat_and_transmission():
    n = reporting_network()
    frame, technologies, _ = prepare_province_peakload_capacity_data(n)
    assert frame.at["Anhui", "Peak Load"] * PLOT_CAP_UNITS == pytest.approx(9)
    assert frame.at["Jiangsu", "Peak Load"] * PLOT_CAP_UNITS == pytest.approx(6)
    assert "heat" not in technologies
    assert "steel" not in technologies
    metrics = calculate_metrics(n, "test", pd.DataFrame())
    assert metrics.at["gross_ac_withdrawal_mwh", "test"] == pytest.approx(44)
    # The simultaneous system peak is 14, not the sum of provincial peaks (15).
    assert metrics.at["peak_gross_ac_withdrawal_mw", "test"] == pytest.approx(14)
    prices = calculate_weighted_prices(n, "test", pd.DataFrame())
    assert prices.at["electricity", "test"] == pytest.approx(920 / 44)


def test_energy_tables_keep_electric_inputs_and_exclude_material_units():
    n = reporting_network()
    balance = calculate_supply_energy(n, "test", pd.DataFrame())
    assert "steel" not in balance.index.get_level_values(0)
    assert balance.at[("AC", "Link", "steel route"), "test"] == pytest.approx(-7)
    assert balance.at[("AC", "Link", "electrolysis"), "test"] == pytest.approx(-10)
    assert "H2" in balance.index.get_level_values(0)
    peak = calculate_peak_dispatch(n, "test", pd.DataFrame())
    assert "steel" not in peak.index.get_level_values(0)
    for calculate in (calculate_capacities, calculate_expanded_capacities):
        capacity = calculate(n, "test", pd.DataFrame())
        assert "steel" not in capacity.index.get_level_values("bus_carrier")


def test_off_mode_preserves_fixed_electricity_and_static_loads():
    n = reporting_network(industry=False)
    frame, _, _ = prepare_province_peakload_capacity_data(n)
    assert frame.at["Anhui", "Peak Load"] * PLOT_CAP_UNITS == pytest.approx(5)
    assert frame.at["Jiangsu", "Peak Load"] * PLOT_CAP_UNITS == pytest.approx(6)
    metrics = calculate_metrics(n, "test", pd.DataFrame())
    assert metrics.at["gross_ac_withdrawal_mwh", "test"] == pytest.approx(27)
    assert metrics.at["peak_gross_ac_withdrawal_mw", "test"] == pytest.approx(9)
    prices = calculate_weighted_prices(n, "test", pd.DataFrame())
    assert prices.at["electricity", "test"] == pytest.approx(630 / 27)


def test_gross_ac_withdrawal_includes_battery_charging_without_discharge_credit():
    n = reporting_network()
    n.add("Carrier", "battery")
    n.add("Bus", "A battery", carrier="battery", unit="MWh", location="Anhui")
    n.add("Link", "battery charger", bus0="A", bus1="A battery", carrier="battery", efficiency=0.9, p_nom=5)
    n.add("Link", "battery discharger", bus0="A battery", bus1="A", carrier="battery", efficiency=0.9, p_nom=5)
    n.links_t.p0["battery charger"] = [5, 0]
    n.links_t.p1["battery charger"] = [-4.5, 0]
    n.links_t.p0["battery discharger"] = [0, 1.5]
    n.links_t.p1["battery discharger"] = [0, -1.35]
    # 4.5 MWh enters the battery; 1.5 MW over three weighted hours leaves it.
    # Neither discharged energy nor round-trip losses define this gross metric.
    n.generators_t.p["A grid"] += [5, -1.35]
    metrics = calculate_metrics(n, "test", pd.DataFrame())
    assert metrics.at["gross_ac_withdrawal_mwh", "test"] == pytest.approx(44 + 5)
    assert metrics.at["peak_gross_ac_withdrawal_mw", "test"] == pytest.approx(14 + 5)
    prices = calculate_weighted_prices(n, "test", pd.DataFrame())
    assert prices.at["electricity", "test"] == pytest.approx((920 + 5 * 10) / 49)
