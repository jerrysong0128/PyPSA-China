# Electricity reporting with material Loads

`plot_statistics.py` provincial peak demand and `make_summary.py` electricity
metrics now use `industry_accounting.electricity_consumption_by_province`:

- Include fixed AC Loads, including static `p_set`, and solved AC-input conversion
  Link `p0` (steel process electricity, electrolysis, heating and other conversion).
- Exclude product Loads in t/h, non-electric Loads, and AC-to-AC transmission.
- Aggregate AC buses by `Bus.location` before taking provincial maxima. Use the
  bus name when the location is absent. The system peak is the maximum of the
  simultaneous sum, not the sum of provincial maxima.
- Compute electricity consumption in MWh with `snapshot_weightings.generators`.
  This is energy represented by the solve, not automatically an annual total.
- Weight the electricity price by this same consumption, time weights and the
  corresponding AC bus marginal prices. A zero-consumption case yields NaN.

The peak/capacity plot restricts capacity statistics to AC bus ports. Generic
summary capacity, expansion, peak-dispatch and energy-balance tables exclude
explicit material Bus units (`t`, `t/h`, `tonne`, `tonnes`, `kg`, `kg/h`). Legacy
empty units remain supported. These generic tables still separate AC, heat and
H2 by bus carrier; summing their carrier rows is not an electricity total.
Material output and inventory belong in the dedicated industry report. Monetary
cost tables retain industrial costs. Other carrier price rows retain their own
native commodity price units; the electricity row is currency/MWh.

The inactive legacy `calculate_energy` routine is not used by `make_summaries` and
has not been redesigned here. Existing unrelated nodal-capacity Link selection
is unchanged. The shared consumption helper uses the model's signed AC-input
conversion convention; this is not a final-energy-only or battery-loss-free
metric for arbitrary reversible storage topologies.

Validation: `tests/test_industry_reporting.py` contains three analytical-dispatch
regressions covering material and heat exclusion, steel and H2 electricity,
static Loads, two AC buses in one province, transmission in both directions,
non-uniform snapshot weights, simultaneous peaks, electricity-weighted prices,
energy tables and industry-off pure-electric compatibility. All three passed
under the project's PyPSA 0.35 environment. These tests verify reporting formulas;
they do not constitute a full national workflow run or validate industrial data.
