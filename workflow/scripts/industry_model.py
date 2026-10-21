"""Continuous, unit-explicit industrial production for PyPSA 0.35.

Steel is measured in tonnes, power in MW and hydrogen/fuels in MWh (LHV).
Route Links use direct electrical input as their capacity reference. No default
technology coefficients are provided: scientific inputs belong in source tables.
"""

from dataclasses import asdict, dataclass
import math

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class SteelRoute:
    name: str
    electricity_mwh_per_t: float
    hydrogen_mwh_per_t: float
    coal_mwh_per_t: float
    gas_mwh_per_t: float
    ore_t_per_t: float
    scrap_t_per_t: float
    direct_co2_t_per_t: float
    new_annual_cost_per_tpy: float
    active_annual_cost_per_tpy: float
    variable_cost_per_t: float
    minimum_load: float = 0.0
    ramp_up_per_hour: float = 1.0
    ramp_down_per_hour: float = 1.0
    capacity_basis_hours: float = 8760.0

    def validate(self):
        if not self.name or self.name.strip() != self.name:
            raise ValueError("Route needs a nonempty, stripped name")
        for key, value in asdict(self).items():
            if key != "name" and (not math.isfinite(value) or value < 0):
                raise ValueError(f"{self.name}: {key} must be finite and nonnegative")
        if self.electricity_mwh_per_t <= 0:
            raise ValueError("Direct electricity must be positive; model byproducts explicitly")
        if self.capacity_basis_hours <= 0 or self.capacity_basis_hours > 8760:
            raise ValueError("capacity_basis_hours must be in (0, 8760]")
        if self.minimum_load > 1:
            raise ValueError("minimum_load must be in [0, 1]")


def chronological_hours(n):
    """Reject representative/disconnected snapshots and inconsistent weights.

    Each snapshot describes an interval of physical hours. A short contiguous
    window is a cyclic test period, not an annual representative-day sample.
    """
    sns = n.snapshots
    if not isinstance(sns, pd.DatetimeIndex) or len(sns) < 2:
        raise ValueError("Industry requires at least two chronological timestamps")
    intervals = np.diff(sns.asi8) / 3.6e12
    if intervals[0] <= 0 or not np.allclose(intervals, intervals[0]):
        raise ValueError("Industry requires regular, contiguous chronology")
    step = float(intervals[0])
    for column in ("objective", "generators", "stores"):
        weights = n.snapshot_weightings[column].to_numpy()
        if not np.allclose(weights, step):
            raise ValueError(f"{column} weights must equal physical interval hours")
    hours = step * len(sns)
    if hours > 8760:
        raise ValueError("Initial industry implementation supports at most 8760 hours")
    return step, hours


def _carrier(n, name, emissions=0.0):
    if name not in n.carriers.index:
        n.add("Carrier", name, co2_emissions=emissions)
    elif not np.isclose(n.carriers.at[name, "co2_emissions"], emissions):
        raise ValueError(f"Conflicting carbon coefficient for {name}")


def add_steel_industry(
    n,
    annual_demand_t: pd.Series,
    capacities: pd.DataFrame,
    routes: list[SteelRoute],
    resources: pd.DataFrame,
    *,
    currency: str,
    inventory_t: pd.Series | None = None,
    inventory_annual_cost_per_t: float = 0.0,
):
    """Attach production, bounded resources, product demand and cyclic inventory.

    capacities columns: province, route, existing_tpy, new_max_tpy.
    resources columns: province, resource, annual_limit, marginal_cost. Resource
    is ore/scrap (tonnes) or coal/gas (MWh LHV); explicit annual limits are required.
    H2 uses an existing provincial '<province> H2' bus and upstream electrolysis.
    Costs must share the energy network's currency/price basis. Annual costs and
    resource limits are prorated for a short validation period; annual capacity
    is converted using each route's source capacity_basis_hours.

    Existing capacity can be active or mothballed for the entire period, while
    new capacity pays full annualized cost. Neither is hourly commitment.
    This function does not remove legacy electricity: the load adapter must do
    so before calling it and separately validate the replacement identity.
    """
    step, hours = chronological_hours(n)
    fraction = hours / 8760.0
    if not currency:
        raise ValueError("An explicit common currency/price basis is required")
    if n.meta.get("industry"):
        raise ValueError("Industry already attached")
    if not routes or len({r.name for r in routes}) != len(routes):
        raise ValueError("Route names must be nonempty and unique")
    for route in routes:
        route.validate()
    route_by_name = {r.name: r for r in routes}
    if annual_demand_t.empty or not annual_demand_t.index.is_unique:
        raise ValueError("Demand must have unique province indices")
    if not np.isfinite(annual_demand_t).all() or (annual_demand_t < 0).any():
        raise ValueError("Annual steel demand must be finite and nonnegative")
    provinces = annual_demand_t.index
    if not provinces.isin(n.buses.index).all():
        raise ValueError("Every province must have an existing AC bus")
    if not n.buses.loc[provinces, "carrier"].eq("AC").all():
        raise ValueError("Provincial steel routes must connect to AC buses")
    caps = capacities.set_index(["province", "route"])
    if not caps.index.is_unique or not caps.index.get_level_values(0).isin(provinces).all():
        raise ValueError("Duplicate capacity rows or unknown provinces")
    if not caps.index.get_level_values(1).isin(route_by_name).all():
        raise ValueError("Unknown capacity route")
    cap_values = caps[["existing_tpy", "new_max_tpy"]]
    if not np.isfinite(cap_values).all().all() or (cap_values < 0).any().any():
        raise ValueError("Capacity bounds must be finite and nonnegative")
    supplies = resources.set_index(["province", "resource"])
    if not supplies.index.is_unique:
        raise ValueError("Duplicate resource rows")
    vals = supplies[["annual_limit", "marginal_cost"]].astype(float)
    if not np.isfinite(vals).all().all() or (vals < 0).any().any():
        raise ValueError("Resource bounds/costs must be finite and nonnegative")
    if inventory_t is None:
        inventory_t = pd.Series(0.0, index=provinces)
    inventory_t = inventory_t.reindex(provinces)
    if not np.isfinite(inventory_t).all() or (inventory_t < 0).any():
        raise ValueError("Inventory needs an explicit finite nonnegative bound per province")
    if not math.isfinite(inventory_annual_cost_per_t) or inventory_annual_cost_per_t < 0:
        raise ValueError("Invalid inventory cost")

    # Validate all external inputs before adding components.
    needs = {}
    for (province, route_name), row in caps.iterrows():
        route = route_by_name[route_name]
        if row.existing_tpy + row.new_max_tpy == 0:
            continue
        if route.hydrogen_mwh_per_t:
            h2_bus = f"{province} H2"
            if h2_bus not in n.buses.index or n.buses.at[h2_bus, "carrier"] != "H2":
                raise ValueError(f"Missing upstream H2 infrastructure for {province}")
        for resource in ("coal", "gas", "ore", "scrap"):
            suffix = "mwh" if resource in ("coal", "gas") else "t"
            if getattr(route, f"{resource}_{suffix}_per_t"):
                if (province, resource) not in supplies.index:
                    raise ValueError(f"Missing bounded {resource} supply for {province}")
                needs[province, resource] = True

    planned = {"Bus": [], "Load": [], "Store": [], "Generator": [], "Link": []}
    for province in provinces:
        planned["Bus"] += [f"{province} steel", f"{province} steel CO2"]
        planned["Load"].append(f"{province} steel demand")
        planned["Store"].append(f"{province} steel inventory")
        planned["Generator"].append(f"{province} steel emissions")
    for province, resource in needs:
        planned["Bus"].append(f"{province} steel {resource}")
        planned["Generator"].append(f"{province} steel {resource}")
    for (province, route_name), row in caps.iterrows():
        for vintage, maximum in (("active", row.existing_tpy), ("new", row.new_max_tpy)):
            if maximum:
                planned["Link"].append(f"{province} steel {route_name} {vintage}")
    for component, names in planned.items():
        collisions = n.static(component).index.intersection(names)
        if len(collisions) or len(names) != len(set(names)):
            raise ValueError(f"Industry {component} name collision: {collisions.tolist()}")

    _carrier(n, "steel product")
    _carrier(n, "steel direct CO2", emissions=1.0)
    for province in provinces:
        n.add("Bus", f"{province} steel", carrier="steel product", unit="t", location=province)
        n.add("Load", f"{province} steel demand", bus=f"{province} steel",
              carrier="steel product", p_set=float(annual_demand_t[province]) / 8760)
        n.add("Store", f"{province} steel inventory", bus=f"{province} steel",
              carrier="steel product", e_nom_extendable=True,
              e_nom_max=float(inventory_t[province]), e_cyclic=True,
              capital_cost=inventory_annual_cost_per_t * fraction)
        n.add("Bus", f"{province} steel CO2", carrier="steel direct CO2", unit="t", location=province)
        # sign=-1 consumes emitted tonnes but positive dispatch contributes to the
        # native primary_energy constraint and existing emission-price function.
        max_emission = sum(
            (row.existing_tpy + row.new_max_tpy) / route_by_name[r].capacity_basis_hours
            * route_by_name[r].direct_co2_t_per_t
            for (p, r), row in caps.iterrows() if p == province
        )
        n.add("Generator", f"{province} steel emissions", bus=f"{province} steel CO2",
              carrier="steel direct CO2", sign=-1, efficiency=1,
              p_nom=max_emission, marginal_cost=0)

    for province, resource in needs:
        supply = supplies.loc[province, resource]
        carrier = f"steel {resource} supply"
        _carrier(n, carrier)  # All steel fossil carbon is counted at the route.
        bus = f"{province} steel {resource}"
        n.add("Bus", bus, carrier=carrier, unit="MWh" if resource in ("coal", "gas") else "t",
              location=province)
        period_limit = float(supply.annual_limit) * fraction
        n.add("Generator", bus, bus=bus, carrier=carrier,
              p_nom=period_limit / step, e_sum_max=period_limit,
              marginal_cost=float(supply.marginal_cost))

    records = []
    for (province, route_name), row in caps.iterrows():
        route = route_by_name[route_name]
        e = route.electricity_mwh_per_t
        carrier = f"steel {route_name}"
        _carrier(n, carrier)
        ports = {"bus0": province, "bus1": f"{province} steel", "efficiency": 1 / e,
                 "bus2": f"{province} steel CO2", "efficiency2": route.direct_co2_t_per_t / e}
        for resource, coefficient in (
            ("H2", route.hydrogen_mwh_per_t), ("coal", route.coal_mwh_per_t),
            ("gas", route.gas_mwh_per_t), ("ore", route.ore_t_per_t), ("scrap", route.scrap_t_per_t),
        ):
            if coefficient:
                port = len([k for k in ports if k.startswith("bus")])
                ports[f"bus{port}"] = f"{province} H2" if resource == "H2" else f"{province} steel {resource}"
                ports[f"efficiency{port}"] = -coefficient / e
        for vintage, maximum, annual_cost in (
            ("active", row.existing_tpy, route.active_annual_cost_per_tpy),
            ("new", row.new_max_tpy, route.new_annual_cost_per_tpy),
        ):
            if maximum == 0:
                continue
            name = f"{province} steel {route_name} {vintage}"
            n.add("Link", name, **ports, carrier=carrier, p_nom_extendable=True,
                  p_nom_max=float(maximum) * e / route.capacity_basis_hours,
                  capital_cost=annual_cost * route.capacity_basis_hours / e * fraction,
                  marginal_cost=route.variable_cost_per_t / e, p_min_pu=route.minimum_load,
                  ramp_limit_up=route.ramp_up_per_hour * step,
                  ramp_limit_down=route.ramp_down_per_hour * step)
            records.append({"name": name, "province": province, "route": route_name,
                            "vintage": vintage, "electricity_mwh_per_t": e,
                            "capacity_basis_hours": route.capacity_basis_hours,
                            "ramp_up": route.ramp_up_per_hour * step,
                            "ramp_down": route.ramp_down_per_hour * step})
    # PyPSA adds extra-port columns dynamically; existing links without that
    # port can otherwise inherit NaN coefficients and trigger consistency warnings.
    for column in n.links.columns:
        if column.startswith("bus") and column[3:].isdigit() and int(column[3:]) >= 2:
            efficiency = f"efficiency{column[3:]}"
            n.links.loc[n.links[column].fillna("").eq(""), efficiency] = 0.0
    n.meta["industry"] = {"version": 1, "currency": currency, "period_hours": hours,
                          "annual_demand_t": annual_demand_t.to_dict(),
                          "routes": [asdict(r) for r in routes], "links": records,
                          "cyclic_ramps_required": True}


def add_industry_constraints(n, snapshots=None):
    """Add last-to-first ramps; native PyPSA handles all interior intervals."""
    records = n.meta.get("industry", {}).get("links", [])
    if not records:
        return
    chronological_hours(n)
    if snapshots is not None and not n.snapshots.equals(pd.Index(snapshots)):
        raise ValueError("Industry cyclic constraints require the complete model period")
    if "Link-p" not in n.model.variables or "Link-p_nom" not in n.model.variables:
        raise ValueError("Industry constraints require extendable route variables")
    for i, record in enumerate(records):
        name = record["name"]
        dispatch = n.model["Link-p"].sel(Link=name)
        capacity = n.model["Link-p_nom"].sel({"Link-ext": name})
        delta = dispatch.isel(snapshot=0) - dispatch.isel(snapshot=-1)
        n.model.add_constraints(delta <= record["ramp_up"] * capacity,
                                name=f"industry-cyclic-ramp-up-{i}")
        n.model.add_constraints(-delta <= record["ramp_down"] * capacity,
                                name=f"industry-cyclic-ramp-down-{i}")


def solved_output(n, component, attribute, indices=None):
    """Read finite solved outputs, restoring only official zero-default columns.

    PyPSA NetCDF export omits columns equal to their component default. An
    imported finite objective establishes stored solution data, not a new proof
    of optimality; a live model must additionally have an optimal termination.
    Existing NaNs and incomplete snapshot indices are never filled.
    """
    if not n.is_solved or not np.isfinite(n.objective):
        raise ValueError("Industrial accounting requires a finite solved objective")
    model = getattr(n, "_model", None)
    if model is not None and (model.status != "ok" or model.termination_condition != "optimal"):
        raise ValueError("Industrial accounting requires an optimal current solve")
    table = n.static(component)
    selected = table.index if indices is None else pd.Index(indices)
    if not selected.isin(table.index).all():
        raise ValueError(f"Unknown {component} components in solved output request")
    frame = n.dynamic(component)[attribute]
    if not frame.index.equals(n.snapshots):
        raise ValueError(f"Missing chronology in solved {component}-{attribute}")
    attrs = n.component_attrs[component].loc[attribute]
    if attrs["status"] != "Output":
        raise ValueError(f"{component}-{attribute} is not an official Output")
    missing = selected.difference(frame.columns)
    if len(missing) and attrs["default"] != 0:
        raise ValueError(f"Missing non-default solved {component}-{attribute} columns")
    result = frame.reindex(columns=selected, fill_value=0.0)
    if not np.isfinite(result).all().all():
        raise ValueError(f"Non-finite solved {component}-{attribute} output")
    return result


def steel_dispatch(n):
    """Return solved route production (t/h) and direct electricity use (MW)."""
    records = n.meta.get("industry", {}).get("links", [])
    coefficients = pd.Series({r["name"]: r["electricity_mwh_per_t"] for r in records})
    electricity = solved_output(n, "Link", "p0", coefficients.index)
    return electricity.divide(coefficients, axis=1), electricity
