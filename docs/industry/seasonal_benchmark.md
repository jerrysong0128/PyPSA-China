# Full-year seasonal technical benchmark

`run_seasonal_benchmark.py` exercises the shared `industry_model` and
`industry_accounting` modules on one synthetic Anhui electricity/steel node.
It retains all 8,760 consecutive physical hourly snapshots in 2030 with unit
weights. There are no representative periods or annual extrapolations.

This is an optional technical benchmark retained from earlier validation. The
current usability check is the [six-hour minimal case](quickstart.md); the user's
2026-10-21 instruction does not require a full-year solve. The recorded outputs
below were read back, not recomputed, during the final minimal-case handover.

```sh
/Users/jerrysong/anaconda3/envs/pypsa-china/bin/python \
  scripts/industry_validation/run_seasonal_benchmark.py --solver highs
```

A Python environment with the repository's PyPSA stack and HiGHS can use `python`
instead of the machine-specific interpreter. `--solver gurobi` is also supported.
Outputs go to `results/industry_seasonal_benchmark/`: one hourly and one monthly
CSV per case, plus `summary.json` containing inputs, costs, capacity decisions,
physical residuals and comparison metrics. Results are generated artifacts.

## Controlled comparison

Both cases use the same 87,600 tonnes annual steel demand, flat delivery rate,
35,000 tCO2 joint annual carbon cap, 5 MW nonsteel load and energy supply.
Grid prices vary smoothly from 40 to 180 synthetic currency units/MWh over the
year; a fixed 10 MW renewable generator has availability 0.20–0.90, highest during
cheap months. Grid capacity is fixed 30 MW and emits 0.35 tCO2/MWh. The steel route
uses 0.8 MWh electricity and 1.1 tonnes scrap per tonne product and emits 0.1 tCO2/t.
All of these are synthetic engineering test values, not plant observations.

Existing steel capacity is bounded 70,080 t/year and new investment 175,200 t/year.
Active capacity costs 0.5 and new capacity 4 currency units per nominal annual
tonne; variable process cost is 2 per produced tonne. Scrap supply has a finite
105,120-tonne annual limit and costs 20 per tonne. The route has minimum load 20%
and ramp limits 10% of installed capacity per physical hour, including the
last-to-first transition. This continuous LP does not model unit commitment.

The baseline has zero stock capacity. The comparison allows investment in up to
7,200 tonnes of product inventory, equivalent to 30 days of this synthetic demand,
at 1 currency unit per tonne capacity annually. **Thirty days is a deliberate
technical test assumption, not a sourced real-world storage cap or a recommended
empirical scenario.** Native cyclic storage plus an explicit zero terminal-stock
constraint enforces zero pre-first-hour and zero end-year stock. No initial steel
is supplied for free. Storage cannot substitute for annual production.

## Acceptance checks

The script fails unless both cases solve optimally, annual production equals
demand, initial and terminal stock close, electricity and CO2 reconcile, and all
core capacity/minimum-load/ramp/material/resource/carbon checks pass. It also
recomputes all objective cost components. It requires a positive cost reduction,
increased production in the lowest-price quartile and decreased production in
the highest-price quartile. Total direct process electricity should remain
unchanged for a single route with identical annual production; its timing changes.

The common carbon cap need not bind: this test validates accounting and cap
compliance, not a carbon-policy response. One synthetic route isolates temporal
flexibility; it does not validate three-route competition, real China demand,
province transfers, inventory realism, or technology cost calibration.

## Recorded run (21 October 2026)

HiGHS 1.14.0 solved the zero-inventory case in 1.75 seconds and the 30-day case in
25.26 seconds (solver/model-build timing, excluding imports). Both were optimal.

| Metric | Zero inventory | Synthetic 30-day inventory |
| --- | ---: | ---: |
| Annual steel production, t | 87,600 | 87,600 |
| Total annual objective, synthetic currency | 10,507,620 | 9,957,836.49 |
| New steel capacity, t/year | 17,520 | 56,455.74 |
| Active existing capacity, t/year | 70,080 | 70,080 |
| Product inventory capacity, t | 0 | 7,200 |
| Low-price-quartile steel production, t | 21,910 | 26,776.74 |
| High-price-quartile steel production, t | 21,910 | 14,710 |
| Annual direct process electricity, MWh | 70,080 | 70,080 |
| Annual grid electricity, MWh | 65,700 | 65,700 |
| Total electricity including nonsteel, MWh | 113,880 | 113,880 |
| Joint direct + grid CO2, t | 31,755 | 31,755 |

Inventory reduces objective cost by 549,783.51 (5.2322%) after paying for more
steel capacity and storage. Electricity shifts away from expensive hours:
high-price-quartile direct steel use falls by 5,760 MWh, while low-price-quartile
use rises by 3,893.40 MWh (the remainder shifts into the middle price quartiles).
Annual energy and emissions are unchanged because this single-route example has
fixed efficiency and does not curtail renewable output in either case. The carbon
cap has 3,245 tonnes slack in both cases; no emissions benefit is claimed.

Initial and terminal inventory are zero. Maximum hourly material-balance error
was 2.77e-10 tonnes, annual production error 1.61e-10 tonnes, and carbon
reconciliation error 1.82e-11 tonnes. Core finite-capacity, minimum-load, cyclic
ramp, inventory, scrap and carbon-cap checks all passed. Objective reconciliation
error was below 8e-7 synthetic currency units. Exact values and route-by-vintage
results are retained in the generated JSON.
