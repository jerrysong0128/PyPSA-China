# Steel LP units and boundaries

`industry_model.py` targets the project's PyPSA 0.35.1 environment. Inputs have
no built-in scientific defaults: the test coefficients are synthetic analytic
fixtures. A route's `electricity_mwh_per_t = e > 0` is **direct** electricity,
excluding electricity consumed upstream to make its hydrogen.

For Link dispatch `p0` in MW, steel production is `q = p0/e` in t/h. The product
port coefficient is `1/e`; each input port is `-input_per_t/e`; the direct CO2
port is `direct_co2_t_per_t/e`. Material port coefficients are conversions between
different units, not dimensionless thermodynamic efficiencies. All fossil route
carbon is counted at the route; industrial coal/gas supply carriers therefore
have zero carbon coefficients. Energy-system electricity and H2 emissions remain
upstream. H2 uses the existing provincial H2 bus and must share its LHV basis.
`direct_co2_t_per_t` includes both fuel combustion and process emissions inside
the route boundary; a process-only coefficient is insufficient.

Annual capacity `A` (t/year) with source rating basis `H` (hours/year) converts to
`p_nom = e*A/H`. Do not apply a second utilization derating. Existing active and
new capacity have separate finite expansion bounds and annualized costs. If an
annual cost is `c` per t/year of capacity, Link cost is `c*H/e`, prorated to the
modeled period in short-window tests. Minimum load is relative to selected active
capacity, not to all historical installed capacity. This is an annual active or
mothballed fraction, not a furnace start/stop model.
When `H < 8760`, the nominal annual capacity is a rating convention, not a hard
annual production limit: continuous operation could produce `A*8760/H` tonnes.
Use `H=8760` when the supplied t/year bound itself must cap annual production.

Annual product demand becomes a constant `A_demand/8760` t/h; annual resource
limits use native weighted `Generator.e_sum_max`. Regular contiguous timestamps
and equal physical objective/generator/store weights are required. Short runs
prorate annual costs and resources by `period_hours/8760` and are explicitly cyclic
test windows. They cannot support annual planning conclusions.

Steel inventory capacity is optimized below a finite tonne bound
(`Store.e_nom_max`) with a cyclic boundary, explicit annual capacity cost and no
losses. The default upper bound is zero; positive bounds require evidence. Native
ramps cover adjacent intervals; the solve
callback `add_industry_constraints` adds both last-to-first inequalities. The
model metadata must be retained across NetCDF export/import for these callbacks.

Direct CO2 flows to a dedicated tonne bus and is consumed by a `sign=-1` Generator
with `co2_emissions=1` and efficiency 1. Its positive dispatch contributes exactly
once to the existing native `primary_energy` limit and carbon-price function.
There is no carbon Store from which emissions can disappear at the boundary.

`steel_dispatch()` returns production (t/h) and direct electricity (MW) separately.
Never sum material loads or material port flows into MW/GWh statistics. Solving
without the cyclic callback is not an accepted industrial solve.
