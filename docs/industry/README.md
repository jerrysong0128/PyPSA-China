# Industrial modelling development

Development base: PIK commit `3ba042b201470e1f8b74e4356247565b4f8aee0d`.
Branch: `codex/industry-steel-2030`. The original PIK checkout is not modified.

The target is scenario-ready industrial infrastructure comparable to *Industrial
overcapacity can enable seasonal flexibility in electricity use*, adapted to
steel. The reference models aluminium; its numerical assumptions are not steel
parameters. PIK remains the owning model. Earth methods are independently
implemented, rather than copying AGPL code into the MIT project.

## Model contract

- Province-level model with plant-level source data and traceable aggregation.
- Full sector electricity accounts. Industrial electricity is separated into
  modelled steel, other ferrous activities, and other industry.
- Endogenous steel replaces exactly the corresponding baseline electricity.
- BF–BOF, scrap EAF, and H2–DRI–EAF; fixed provincial annual crude-steel demand;
  endogenous investment and dispatch in an initial independent 2030 run.
- Existing annual active capacity and new capacity are separate continuous LP
  decisions. Active capacity is not hourly unit commitment.
- Finite configurable inventory, minimum operation, and chronological ramping.
  Product inventory defaults to zero until an applicable finite bound is sourced.
- Explicit material/energy units and hydrogen boundary; no double counting of
  electrolysis or route direct emissions.
- Joint electricity/heat/steel direct CO2 accounting. Reconstruct the 2020 steel
  baseline before applying the existing 2030 reduction as an experimental case.
- No implicit unconstrained interprovincial steel transport.
- New functionality is disabled by default. Existing electricity and EV modes
  remain usable independently.

## Data contract

`data/industry/raw/` retains original downloaded bytes and extracted source
files, and is ignored by Git. `sources/` records URLs, versions, retrieval dates,
licences and checksums. `processed/` contains redistributable normalized tables.
Processing code must reproduce these tables. Missing observations are not zero.
Every estimate needs its method, input sources, geography and year. Synthetic
test fixtures must never be described as observed provincial data.

## Acceptance gates

1. Reproducible sources, coverage/units/year validation, and explicit estimates.
2. Hourly and annual sector conservation; exact steel baseline replacement.
3. Route material and energy balances, separate existing/new cost conversion.
4. Finite inventory, weighted scrap limits, cyclic and ordinary ramp checks.
5. Direct + upstream CO2 reconciliation, binding cap and price perturbations.
6. Workflow combinations with industry off/fixed/endogenous and EV off/on.
7. Electrical reserves and reporting exclude material units and include process
   electricity; solved networks retain physically consistent industrial flows.
8. Small analytic LPs, 31-province chronological smoke case, then a full-year
   hourly 2030 run with reproducible configuration and validation reports.
9. A reference capability comparison explicitly distinguishes implemented,
   validated, pending, and unavailable upstream features. Solver success alone
   does not satisfy these gates.

Progress and actual cherry-pick dependencies are recorded in
`commit_dependencies.md`. No scientific conclusion about future steel technology
shares follows from demonstration scenarios.
