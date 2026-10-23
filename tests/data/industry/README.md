# Reviewed industry evidence fixtures

`evidence/` contains expected normalized CSV snapshots for portable regression
tests. They were generated from the pinned sources in
`resources/data/industry/sources/manifest.json` and checked against source units,
missing-value handling, nested electricity totals and GEM release coverage.
They preserve source IDs and cell/line locators. GEM attribution: Global Energy
Monitor, Global Iron and Steel Tracker, September 2026 V1, CC BY 4.0.

These are test expectations, not model inputs. Production tables are rebuilt to
`resources/derived_data/industry/evidence/`. Compare a fresh build against these
snapshots; source updates require an independently reviewed fixture change.
The old 2024 plant-capacity and 2019–2022 production snapshots have been replaced
by September 2026 capacity and 2019–2025 source-cell records.
