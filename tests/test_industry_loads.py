"""Conservation, time basis, and failure cases for industrial load splitting."""

import numpy as np
import pandas as pd
import pytest

from industry_loads import split_industry_loads


@pytest.fixture
def inputs():
    total = pd.DataFrame({"Hebei": [10., 20., 30., 40.], "Beijing": [4., 2., 3., 1.]},
                         index=pd.date_range("2030-01-01", periods=4, freq="h"))
    weights = pd.Series(2190., index=total.index)
    shares = {"agriculture": .05, "industry": .55, "construction": .05,
              "services": .10, "residential": .15, "steel": .20, "other_ferrous": .10}
    totals = total.mul(weights, axis=0).sum()
    annual = pd.DataFrame([{"year": 2030, "province": p, "sector": s, "value": totals[p] * v,
                            "unit": "MWh", "source_id": "fixture", "estimate_flag": True}
                           for p in total for s, v in shares.items()])
    return total, annual, weights


def provincial_sum(frame):
    return frame.T.groupby(level="province", sort=False).sum().T.rename_axis(columns=None)


def test_fixed_conserves_hourly_and_weighted_annual_electricity(inputs):
    total, annual, weights = inputs
    before = annual.copy(deep=True)
    result = split_industry_loads(total, annual, planning_year=2030, snapshot_weightings=weights)
    pd.testing.assert_frame_equal(provincial_sum(result.fixed_loads_mw), total)
    pd.testing.assert_frame_equal(provincial_sum(result.top_level_mw), total)
    for profile in [result.top_level_mw, result.industry_loads_mw]:
        actual = profile.mul(weights, axis=0).sum()
        for (province, sector), value in actual.items():
            assert value == pytest.approx(result.annual_targets_mwh.loc[province, sector])
    assert result.annual_targets_mwh.loc["Hebei", "other_industry"] == pytest.approx(54750.)
    pd.testing.assert_frame_equal(annual, before)
    pd.testing.assert_frame_equal(result.total_load_mw, total)


def test_endogenous_removes_steel_exactly_once(inputs):
    total, annual, weights = inputs
    result = split_industry_loads(total, annual, planning_year=2030, mode="endogenous", snapshot_weightings=weights)
    assert "steel" not in result.fixed_loads_mw.columns.get_level_values("sector")
    assert "other_ferrous" in result.fixed_loads_mw.columns.get_level_values("sector")
    pd.testing.assert_frame_equal(provincial_sum(result.fixed_loads_mw) + result.steel_baseline_mw.rename_axis(columns=None), total)
    np.testing.assert_allclose(result.steel_baseline_mw, total * .2)


def test_off_preserves_original_short_window_without_annual_data(inputs):
    total, _, _ = inputs
    total = total.astype(int)
    result = split_industry_loads(total, planning_year=2030, mode="off")
    pd.testing.assert_frame_equal(result.total_load_mw, total)
    pd.testing.assert_frame_equal(provincial_sum(result.fixed_loads_mw), total)
    assert not result.steel_baseline_mw.to_numpy().any()
    result.total_load_mw.iloc[0, 0] = 999
    assert total.iloc[0, 0] == 10


def test_short_window_requires_full_year_denominator(inputs):
    total, annual, weights = inputs
    with pytest.raises(ValueError, match="full annual"):
        split_industry_loads(total, annual, planning_year=2030)
    annual_total = total.mul(weights, axis=0).sum()
    result = split_industry_loads(total.iloc[:2], annual, planning_year=2030, annual_total_mwh=annual_total)
    np.testing.assert_allclose(result.steel_baseline_mw, total.iloc[:2] * .2)
    assert result.steel_baseline_mw.sum().sum() < annual.query("sector == 'steel'").value.sum()


def test_explicit_province_mapping_and_no_implicit_aliases(inputs):
    total, annual, weights = inputs
    annual["province"] = annual.province.replace({"Hebei": "河北省"})
    with pytest.raises(ValueError, match="provinces"):
        split_industry_loads(total, annual, planning_year=2030, snapshot_weightings=weights)
    result = split_industry_loads(total, annual, planning_year=2030, snapshot_weightings=weights,
                                  province_mapping={"河北省": "Hebei"})
    pd.testing.assert_frame_equal(provincial_sum(result.fixed_loads_mw), total)


@pytest.mark.parametrize("change,match", [
    (lambda a: a.assign(year=2022), "project calibration"),
    (lambda a: a.assign(unit="TWh"), "unit must be MWh"),
    (lambda a: a.assign(value=np.nan), "missing"),
    (lambda a: a.assign(value=-1), "nonnegative"),
    (lambda a: a.assign(value=np.inf), "finite"),
    (lambda a: a[a.sector != "other_ferrous"], "missing required"),
    (lambda a: pd.concat([a, a.iloc[:1]]), "duplicate"),
    (lambda a: a.assign(sector=a.sector.replace({"industry": "secondary_industry"})), "unknown sectors"),
    (lambda a: a.assign(province="unknown"), "provinces"),
    (lambda a: a.assign(value=np.where(a.sector == "industry", a.value * 3, a.value)), "shares exceed"),
    (lambda a: a.assign(value=np.where(a.sector == "steel", a.value * 3, a.value)), "shares exceed"),
])
def test_invalid_annual_inputs_fail_closed(inputs, change, match):
    total, annual, weights = inputs
    with pytest.raises(ValueError, match=match):
        split_industry_loads(total, change(annual), planning_year=2030, snapshot_weightings=weights)


def test_supplied_residual_must_agree(inputs):
    total, annual, weights = inputs
    remainder = annual[annual.sector == "agriculture"].assign(sector="residual", value=0.)
    with pytest.raises(ValueError, match="supplied residual"):
        split_industry_loads(total, pd.concat([annual, remainder]), planning_year=2030, snapshot_weightings=weights)


def test_zero_demand_province_and_explicit_missing_zero(inputs):
    total, annual, weights = inputs
    total["Beijing"] = 0.
    annual.loc[annual.province == "Beijing", "value"] = 0.
    result = split_industry_loads(total, annual, planning_year=2030, snapshot_weightings=weights)
    assert np.isfinite(result.fixed_loads_mw.to_numpy()).all()
    assert not result.fixed_loads_mw["Beijing"].to_numpy().any()
    annual = annual.drop(annual[(annual.province == "Beijing") & (annual.sector == "steel")].index)
    with pytest.raises(ValueError, match="missing required"):
        split_industry_loads(total, annual, planning_year=2030, snapshot_weightings=weights)


def test_time_weights_and_leap_year_contract(inputs):
    total, annual, weights = inputs
    with pytest.raises(ValueError, match="exactly match"):
        split_industry_loads(total, annual, planning_year=2030, snapshot_weightings=weights.iloc[::-1])
    with pytest.raises(ValueError, match="strictly positive"):
        split_industry_loads(total, annual, planning_year=2030, snapshot_weightings=weights * 0)
    with pytest.raises(ValueError, match="full annual"):
        split_industry_loads(total, annual.assign(year=2032), planning_year=2032, snapshot_weightings=weights)
    result = split_industry_loads(total, annual.assign(year=2032), planning_year=2032,
                                  snapshot_weightings=weights * 8784 / 8760)
    assert result.annual_total_mwh["Hebei"] == pytest.approx(219600.)


def test_full_year_explicit_denominator_must_match(inputs):
    total, annual, weights = inputs
    with pytest.raises(ValueError, match="integral disagrees"):
        split_industry_loads(total, annual, planning_year=2030, snapshot_weightings=weights,
                             annual_total_mwh=total.mul(weights, axis=0).sum() * 2)


def test_hourly_weather_year_may_differ_from_planning_year():
    total = pd.DataFrame({"Hebei": 1.}, index=pd.date_range("2019-01-01", periods=8760, freq="h"))
    annual = pd.DataFrame([{"year": 2030, "province": "Hebei", "sector": s, "value": 0.}
                           for s in ["agriculture", "industry", "construction", "services", "residential", "steel", "other_ferrous"]])
    result = split_industry_loads(total, annual, planning_year=2030, mode="fixed")
    assert result.mode == "fixed_load"
    assert result.annual_targets_mwh.loc["Hebei", "residual"] == 8760.
    pd.testing.assert_frame_equal(provincial_sum(result.fixed_loads_mw), total)
