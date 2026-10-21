# Commit dependencies

Base: `3ba042b201470e1f8b74e4356247565b4f8aee0d` (PIK main).

This document lists logical modules. Actual commit IDs are filled in only after
the corresponding work is committed. A later ledger commit can reference prior
commits without a self-referential hash. Cherry-pick dependencies in order.

| Module | Scope | Requires | Status |
| --- | --- | --- | --- |
| C0 | Development contract and raw-data exclusion | base | initial commit |
| C1 | Download provenance, processing, normalized inputs | C0 | pending |
| C2 | Sector-load decomposition and conservation | C0 | pending |
| C3 | Steel baseline extraction and replacement | C1, C2 | pending |
| C4 | Route conversion, resources and investment | C0 | pending |
| C5 | Joint carbon baseline and budget | C1, C4 | pending |
| C6 | Finite inventory and operational constraints | C4 | pending |
| C7 | Workflow, reserves and reporting integration | C3, C5, C6 | pending |
| C8 | 2030 scenarios and end-to-end validation | C7 | pending |

Tests should accompany their owning module. Reference-only documentation and
source provenance must not create hidden runtime dependencies. Keep general
load decomposition usable without endogenous steel components.
