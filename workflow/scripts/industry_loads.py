"""Conservative sector decomposition of provincial electricity demand.

This is an original implementation; no PyPSA-Earth source is incorporated.
All profiles are MW and all annual inputs are MWh. Sector shapes inherit the
provincial total shape: this is an explicit proportional allocation assumption,
not measured sector-specific hourly demand. ``industry`` excludes construction.
``other_ferrous`` is non-steel ferrous activity, never all industrial activity.
"""

import calendar
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd


TOP_LEVEL_SECTORS = (
    "agriculture", "industry", "construction", "services", "residential", "residual"
)
INDUSTRY_SECTORS = ("steel", "other_ferrous", "other_industry")
_REQUIRED = set(TOP_LEVEL_SECTORS[:-1]) | {"steel", "other_ferrous"}
_ALLOWED = set(TOP_LEVEL_SECTORS) | set(INDUSTRY_SECTORS)


@dataclass(frozen=True)
class IndustryLoadSplit:
    """Profiles with (province, sector) columns, except the provincial baselines.

    ``fixed_loads_mw`` is the only profile to attach as fixed electrical Loads.
    Do not also attach ``top_level_mw`` or ``industry_loads_mw``: they overlap.
    ``total_load_mw`` always preserves the original provincial load interface.
    In endogenous mode steel baseline is absent from fixed loads and must be
    replaced by process electricity consumption, not another fixed Load.
    """

    mode: str
    planning_year: int
    total_load_mw: pd.DataFrame
    top_level_mw: pd.DataFrame
    industry_loads_mw: pd.DataFrame
    fixed_loads_mw: pd.DataFrame
    steel_baseline_mw: pd.DataFrame
    annual_targets_mwh: pd.DataFrame
    annual_total_mwh: pd.Series


def _nonnegative_numeric(values, label):
    try:
        numeric = values.astype(float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must contain numeric values") from exc
    if not np.isfinite(numeric.to_numpy()).all() or (numeric.to_numpy() < 0).any():
        raise ValueError(f"{label} must be finite and nonnegative; missing values are not zero")
    return numeric


def _empty_profiles(index):
    return pd.DataFrame(
        index=index,
        columns=pd.MultiIndex.from_tuples([], names=["province", "sector"]),
        dtype=float,
    )


def _profiles(total, annual, annual_total, sectors):
    result = {}
    for province in total.columns:
        denominator = annual_total[province]
        for sector in sectors:
            share = annual.loc[province, sector] / denominator if denominator else 0.0
            result[(province, sector)] = total[province] * share
    frame = pd.DataFrame(result, index=total.index)
    frame.columns.names = ["province", "sector"]
    return frame


def split_industry_loads(
    total_load_mw: pd.DataFrame,
    annual_demand_mwh: pd.DataFrame | None = None,
    *,
    planning_year: int,
    mode: str = "fixed_load",
    snapshot_weightings: pd.Series | None = None,
    annual_total_mwh: pd.Series | None = None,
    province_mapping: Mapping[str, str] | None = None,
) -> IndustryLoadSplit:
    """Split total electricity into sectors without changing its hourly sum.

    Annual data is a tidy table with ``year, province, sector, value`` columns.
    An optional ``unit`` column must contain only ``MWh``; other metadata columns
    (source_id, estimate_flag, etc.) are accepted and never modified. All rows
    must have year == planning_year: projections/calibration of older shares
    must happen explicitly upstream. All provinces and required sectors must be
    present, including explicit zeros; unknown provinces/sectors fail closed.
    Province aliases are matched only through the supplied mapping.

    Required sectors: agriculture, industry, construction, services, residential,
    steel, other_ferrous. Residual and other_industry are derived by subtraction;
    if supplied, they must agree. Steel and other_ferrous are subsets of industry.
    Second-industry statistics containing construction must be converted upstream.

    With no annual_total_mwh, the input must represent a complete planning year:
    weights sum to 8760 (8784 in a leap year). Default weights of 1 require hourly
    timestamps. Split the full year before selecting short solve windows. For a
    preselected window, annual_total_mwh must explicitly supply each province's
    FULL-year electricity; shares are never normalized to the short window.

    Modes: off returns the original aggregate load without requiring annual data;
    fixed_load returns all disaggregated loads (fixed is an accepted alias);
    endogenous removes ONLY steel baseline from fixed electrical loads.
    """
    if mode == "fixed":
        mode = "fixed_load"
    if mode not in {"off", "fixed_load", "endogenous"}:
        raise ValueError("mode must be off, fixed_load, or endogenous")
    if isinstance(planning_year, bool) or not isinstance(planning_year, (int, np.integer)):
        raise ValueError("planning_year must be an integer calendar year")
    if not 1 <= planning_year <= 9999:
        raise ValueError("planning_year must be an integer calendar year")
    if not isinstance(total_load_mw, pd.DataFrame) or total_load_mw.empty:
        raise ValueError("total_load_mw must be a nonempty DataFrame")
    if not isinstance(total_load_mw.index, pd.DatetimeIndex):
        raise ValueError("total_load_mw must have a DatetimeIndex")
    if not total_load_mw.index.is_unique or not total_load_mw.index.is_monotonic_increasing:
        raise ValueError("load timestamps must be unique and increasing")
    if total_load_mw.index.hasnans or not total_load_mw.columns.is_unique:
        raise ValueError("load timestamps and province columns must be unique and nonmissing")
    if any(not isinstance(p, str) or not p for p in total_load_mw.columns):
        raise ValueError("province columns must be nonempty strings")
    total = _nonnegative_numeric(total_load_mw, "total_load_mw")
    empty = _empty_profiles(total.index)
    zero_steel = total * 0.0
    if mode == "off":
        fixed = total_load_mw.copy(deep=True)
        fixed.columns = pd.MultiIndex.from_product([total.columns, ["total"]], names=["province", "sector"])
        return IndustryLoadSplit(mode, planning_year, total_load_mw.copy(deep=True),
                                 empty.copy(), empty.copy(), fixed, zero_steel,
                                 pd.DataFrame(index=total.columns), pd.Series(dtype=float))

    if snapshot_weightings is None:
        if len(total.index) > 1 and not (total.index.to_series().diff().iloc[1:] == pd.Timedelta(hours=1)).all():
            raise ValueError("non-hourly snapshots require explicit snapshot_weightings in hours")
        weights = pd.Series(1.0, index=total.index)
    else:
        if not isinstance(snapshot_weightings, pd.Series) or not snapshot_weightings.index.equals(total.index):
            raise ValueError("snapshot_weightings must exactly match load timestamps and ordering")
        weights = _nonnegative_numeric(snapshot_weightings, "snapshot_weightings")
        if (weights <= 0).any():
            raise ValueError("snapshot_weightings must be strictly positive hours")
    annual_hours = 8784 if calendar.isleap(planning_year) else 8760
    represented_hours = weights.sum()
    full_year = np.isclose(represented_hours, annual_hours, rtol=0, atol=1e-6)
    integrated = total.mul(weights, axis=0).sum()
    if represented_hours > annual_hours + 1e-6:
        raise ValueError("snapshot weights exceed the planning year's hours")
    if annual_total_mwh is None:
        if not full_year:
            raise ValueError("provide a full annual profile/weights or explicit annual_total_mwh; never normalize annual demand into a short window")
        annual_total = integrated
    else:
        if not isinstance(annual_total_mwh, pd.Series) or not annual_total_mwh.index.is_unique:
            raise ValueError("annual_total_mwh must be a Series with unique province index")
        if set(annual_total_mwh.index) != set(total.columns):
            raise ValueError("annual_total_mwh must contain exactly the load provinces")
        annual_total = _nonnegative_numeric(annual_total_mwh.reindex(total.columns), "annual_total_mwh")
        if full_year and not np.allclose(integrated, annual_total, rtol=1e-9, atol=1e-6):
            raise ValueError("full-year load integral disagrees with annual_total_mwh")
        if (integrated > annual_total + np.maximum(1e-6, annual_total * 1e-9)).any():
            raise ValueError("window electricity exceeds annual_total_mwh")

    required_columns = {"year", "province", "sector", "value"}
    if not isinstance(annual_demand_mwh, pd.DataFrame) or not required_columns.issubset(annual_demand_mwh.columns):
        raise ValueError("annual_demand_mwh requires year, province, sector, value columns")
    annual = annual_demand_mwh.copy(deep=True)
    if annual.empty or annual[list(required_columns)].isna().any().any():
        raise ValueError("annual demand is empty or contains missing values")
    years = pd.to_numeric(annual.year, errors="coerce")
    if not (years == planning_year).all():
        raise ValueError("annual demand year must equal planning_year; project calibration years explicitly upstream")
    if "unit" in annual and not annual.unit.eq("MWh").all():
        raise ValueError("annual demand unit must be MWh; convert units explicitly upstream")
    annual["value"] = _nonnegative_numeric(annual.value, "annual demand values")
    if province_mapping is not None:
        annual["province"] = annual.province.map(lambda p: province_mapping.get(p, p))
    if set(annual.province) != set(total.columns):
        raise ValueError("annual demand provinces must exactly match load provinces after explicit mapping")
    unknown = set(annual.sector) - _ALLOWED
    if unknown:
        raise ValueError(f"unknown sectors: {sorted(unknown)}")
    if annual.duplicated(["province", "sector"]).any():
        raise ValueError("duplicate province/sector rows (including alias collisions) are not allowed")
    annual = annual.pivot(index="province", columns="sector", values="value").reindex(total.columns)
    missing = _REQUIRED - set(annual.columns)
    if missing or annual.reindex(columns=sorted(_REQUIRED)).isna().any().any():
        raise ValueError("missing required sector values; supply explicit zeros for each province")

    def remainder(name, parent, children):
        value = parent - annual[list(children)].sum(axis=1)
        tolerance = np.maximum(1e-6, parent * 1e-9)
        if (value < -tolerance).any():
            raise ValueError(f"{name}: sector/subsector shares exceed their parent electricity")
        value = value.clip(lower=0)
        if name in annual:
            if annual[name].isna().any() or not np.allclose(annual[name], value, rtol=1e-9, atol=1e-6):
                raise ValueError(f"supplied {name} disagrees with the parent-minus-children remainder")
        annual[name] = value

    remainder("residual", annual_total, TOP_LEVEL_SECTORS[:-1])
    remainder("other_industry", annual.industry, ["steel", "other_ferrous"])
    top = _profiles(total, annual, annual_total, TOP_LEVEL_SECTORS)
    industry = _profiles(total, annual, annual_total, INDUSTRY_SECTORS)
    fixed_sectors = tuple(s for s in TOP_LEVEL_SECTORS if s != "industry") + INDUSTRY_SECTORS
    if mode == "endogenous":
        fixed_sectors = tuple(s for s in fixed_sectors if s != "steel")
    fixed = _profiles(total, annual, annual_total, fixed_sectors)
    steel = industry.xs("steel", axis=1, level="sector").copy()
    return IndustryLoadSplit(mode, planning_year, total_load_mw.copy(deep=True), top,
                             industry, fixed, steel, annual, annual_total.copy())
