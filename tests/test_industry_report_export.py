"""Solved dispatch, period scaling and NetCDF/CSV roundtrip reporting checks."""
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd
import pypsa
import pytest

from industry_model import SteelRoute, add_industry_constraints, add_steel_industry
from industry_reporting import export_industry_reports


def solved_network(*, baseline=True, empty_resources=False):
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=2, freq="3h"))
    n.snapshot_weightings[:] = 3.0
    for name, carbon in [("AC", 0), ("grid", 0.1), ("H2", 0)]:
        n.add("Carrier", name, co2_emissions=carbon)
    n.add("Bus", "Anhui", carrier="AC")
    n.add("Bus", "Anhui H2", carrier="H2")
    n.add("Load", "remaining fixed", bus="Anhui", p_set=1.0)
    n.add("Generator", "grid", bus="Anhui", carrier="grid", p_nom=20, marginal_cost=10)
    n.add("Link", "electrolysis", bus0="Anhui", bus1="Anhui H2", p_nom=20,
          efficiency=0.5, marginal_cost=3)
    route = SteelRoute(name="test-process", electricity_mwh_per_t=0.5,
        hydrogen_mwh_per_t=0.4, coal_mwh_per_t=0 if empty_resources else 0.2,
        gas_mwh_per_t=0 if empty_resources else 0.1,
        ore_t_per_t=0 if empty_resources else 1.5,
        scrap_t_per_t=0 if empty_resources else 0.3, direct_co2_t_per_t=0.2,
        new_annual_cost_per_tpy=2, active_annual_cost_per_tpy=1,
        variable_cost_per_t=7, capacity_basis_hours=8000)
    resources = pd.DataFrame([dict(province="Anhui", resource=r,
        annual_limit=10 * 8760, marginal_cost=price)
        for r, price in [("coal", 2), ("gas", 3), ("ore", 4), ("scrap", 5)]],
        columns=["province", "resource", "annual_limit", "marginal_cost"])
    if empty_resources:
        resources = resources.iloc[:0]
    # Existing rating of 8000 t/year means 1 t/hour; new capacity is required.
    capacities = pd.DataFrame([dict(province="Anhui", route=route.name,
                                    existing_tpy=8000, new_max_tpy=24000)])
    add_steel_industry(n, pd.Series({"Anhui": 2 * 8760}), capacities, [route], resources,
        currency="synthetic_EUR2020", inventory_t=pd.Series({"Anhui": 0}),
        inventory_annual_cost_per_t=5)
    if baseline:
        n.meta["industry_loads"] = dict(mode="endogenous",
            baseline_snapshots=n.snapshots.astype(str).tolist(),
            steel_baseline_mw={"Anhui": [0.7, 0.7]},
            original_period_mwh={"Anhui": 10.2}, fixed_load_names=["remaining fixed"])
    status = n.optimize(solver_name="highs", extra_functionality=add_industry_constraints,
                        log_to_console=False)
    assert status == ("ok", "optimal")
    return n


def read_reports(paths):
    return {key: pd.read_csv(path) for key, path in paths.items() if key != "audit"}


def test_solved_quantities_capacity_costs_and_load_replacement(tmp_path):
    n = solved_network()
    paths = export_industry_reports(n, tmp_path)
    data = read_reports(paths)
    rows = data["routes"].set_index("vintage")
    assert set(rows.index) == {"active", "new"}
    assert rows.capacity_tpy.tolist() == pytest.approx([8000, 8000])
    assert rows.period_production_t.tolist() == pytest.approx([6, 6])
    assert rows.utilisation_fraction.tolist() == pytest.approx([1, 1])
    assert rows.period_hours.eq(6).all()
    assert not rows.annual_result.any()
    # Already-prorated Link costs must not be multiplied by 6/8760 twice.
    assert rows.period_capacity_cost.sum() == pytest.approx(24000 * 6 / 8760)
    assert rows.period_variable_cost.sum() == pytest.approx(12 * 7)
    for column, total in {"period_direct_electricity_mwh": 6,
            "period_h2_mwh_lhv": 4.8, "period_coal_mwh_lhv": 2.4,
            "period_gas_mwh_lhv": 1.2, "period_ore_t": 18,
            "period_scrap_t": 3.6, "period_direct_co2_t": 2.4}.items():
        assert rows[column].sum() == pytest.approx(total)
    resources = data["resources"].set_index("resource")
    assert resources.annual_limit.tolist() == pytest.approx([87600] * 4)
    assert resources.period_limit.tolist() == pytest.approx([60] * 4)
    assert resources.period_supply_cost.sum() == pytest.approx(2.4*2 + 1.2*3 + 18*4 + 3.6*5)
    # Reconcile objective by adding resource and upstream costs exactly once.
    route_cost = rows.period_process_cost.sum()
    upstream = (n.generators_t.p.grid * 3 * 10).sum() + (n.links_t.p0.electrolysis * 3 * 3).sum()
    assert route_cost + resources.period_supply_cost.sum() + upstream == pytest.approx(n.objective)
    inventory = data["inventory"].iloc[0]
    assert inventory.capacity_t == pytest.approx(0)
    assert inventory.initial_inventory_t == pytest.approx(0)
    assert inventory.final_inventory_t == pytest.approx(0)
    replacement = data["electricity_replacement"].iloc[0]
    assert replacement.removed_steel_baseline_mwh == pytest.approx(4.2)
    assert replacement.original_period_electricity_mwh == pytest.approx(10.2)
    assert replacement.endogenous_process_mwh == pytest.approx(6)
    assert replacement.gross_ac_withdrawal_mwh == pytest.approx(21.6)
    assert replacement.other_conversion_withdrawal_mwh == pytest.approx(9.6)
    assert replacement.process_minus_baseline_mwh == pytest.approx(1.8)
    assert replacement.baseline_reconstruction_error_mwh == pytest.approx(0)
    audit = json.loads(Path(paths["audit"]).read_text())
    assert audit["currency"] == "synthetic_EUR2020"
    assert audit["accounting"]["steel_direct_co2_t"] == pytest.approx(2.4)
    assert audit["provenance"]["data_status"] == "unknown"
    assert audit["provenance"]["manifest_status"] == "not_provided"
    assert rows.data_status.eq("unknown").all()


def test_zero_capacity_empty_resources_and_missing_audit_are_explicit(tmp_path):
    n = solved_network(baseline=False, empty_resources=True)
    # Give existing capacity the whole demand; costly new investment is unused.
    n.links.loc[n.links.carrier.eq("steel test-process") & n.links.index.str.endswith("active"), "p_nom_max"] = 2.0
    assert n.optimize(solver_name="highs", extra_functionality=add_industry_constraints,
                      log_to_console=False) == ("ok", "optimal")
    data = read_reports(export_industry_reports(n, tmp_path))
    new = data["routes"].set_index("vintage").loc["new"]
    assert new.capacity_tpy == pytest.approx(0)
    assert not new.utilisation_defined
    assert pd.isna(new.utilisation_fraction)
    assert data["resources"].empty
    assert "period_used" in data["resources"].columns
    replacement = data["electricity_replacement"].iloc[0]
    assert replacement.baseline_status == "baseline_audit_unavailable"
    assert pd.isna(replacement.removed_steel_baseline_mwh)
    assert pd.isna(replacement.original_period_electricity_mwh)


def test_exported_solved_netcdf_cli_roundtrip(tmp_path):
    n = solved_network()
    # Save provenance with the solved network; reports must not infer it from
    # whichever files happen to be present in the current working directory.
    provenance = {
        "version": 1, "manifest_status": "checksums_verified",
        "data_status": "engineering_validation_only",
        "manifest": {"path": "fixture/manifest.json", "sha256": "a" * 64},
        "assumptions": {"demand": "synthetic constant demand"},
        "input_coverage": {"industry_annual_demand": {
            "rows": 1, "estimated_rows": 1, "non_estimated_rows": 0,
            "unknown_estimate_rows": 0, "rows_missing_source_id": 0,
            "source_ids": ["synthetic-test"],
            "row_provenance": [{"province": "Anhui", "source_id": "synthetic-test",
                                "estimate_flag": True}],
        }},
    }
    n.meta["industry"]["provenance"] = provenance
    file = tmp_path / "solved.nc"
    n.export_to_netcdf(file)
    script = Path(__file__).resolve().parents[1] / "workflow/scripts/industry_reporting.py"
    command = [sys.executable, str(script), str(file), str(tmp_path / "cli")]
    run = subprocess.run(command, check=True, capture_output=True, text=True)
    paths = json.loads(run.stdout)
    rows = pd.read_csv(paths["routes"])
    assert rows.period_production_t.sum() == pytest.approx(12)
    assert set(rows.vintage) == {"active", "new"}
    audit = json.loads(Path(paths["audit"]).read_text())
    assert audit["period_hours"] == 6
    assert audit["tables"]["routes"]["rows"] == 2
    assert audit["provenance"] == provenance
    assert rows.data_status.eq("engineering_validation_only").all()
    assert rows.provenance_manifest_status.eq("checksums_verified").all()


def test_failed_physical_validation_does_not_write_reports(tmp_path):
    n = solved_network()
    n.links_t.p0.loc[:, "Anhui steel test-process active"] = 100
    destination = tmp_path / "invalid"
    with pytest.raises(ValueError, match="failed physical checks"):
        export_industry_reports(n, destination)
    assert not destination.exists()
