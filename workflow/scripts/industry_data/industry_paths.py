"""Shared source and generated-data paths for the PIK industry workflow."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "resources/data/industry"
DERIVED = ROOT / "resources/derived_data/industry"
SOURCE_TABLES = DERIVED / "source_tables"
EVIDENCE = DERIVED / "evidence"
VALIDATION = DERIVED / "validation"
EVIDENCE_FILES = (
    "bachorz_process_parameter_candidates.csv",
    "gem_china_plant_capacity_2026.csv",
    "gem_china_plant_production_2019_2025.csv",
    "gem_province_capacity_2026.csv",
    "henan_sector_electricity_2024.csv",
    "national_sector_electricity_2020.csv",
    "nbs_province_steel_production_2020.csv",
    "route_parameter_candidates.csv",
)
VALIDATION_FILES = (
    "sector_electricity_2030.csv",
    "steel_capacities_2030.csv",
    "steel_demand_2030.csv",
    "steel_direct_co2_baseline_2020.csv",
    "steel_inventory_2030.csv",
    "steel_resources_2030.csv",
    "steel_routes_2030.yaml",
    "config.yaml",
    "manifest.json",
)


def source_inputs(manifest_path, workbooks_only=False):
    """Declare source files, including nested snapshot files, as DAG dependencies."""
    manifest_path = Path(manifest_path)
    data = manifest_path.parent.parent
    paths = {manifest_path}
    for source in json.loads(manifest_path.read_text())["sources"]:
        if workbooks_only and not source.get("csv_export_directory"):
            continue
        if source.get("original_path"):
            paths.add(data / source["original_path"])
        if workbooks_only:
            continue
        paths.update(data / entry["path"] for entry in source.get("additional_files", []))
        if source.get("repository_directory"):
            directory = data / source["repository_directory"]
            paths.add(directory)
            paths.update(p for p in directory.rglob("*") if p.is_file() and p.name != ".DS_Store")
    return sorted(map(str, paths))
