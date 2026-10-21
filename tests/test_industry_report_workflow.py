"""Exercise the actual postprocessing rule through the Snakemake CLI."""
import json
from pathlib import Path
import subprocess
import sys

import pandas as pd
import pytest

from tests.test_industry_report_export import solved_network


ROOT = Path(__file__).resolve().parents[1]


def workflow_file(tmp_path, mode):
    """Supply paths/config only; include the unchanged production rule file."""
    snakefile = tmp_path / "Snakefile"
    snakefile.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(ROOT / 'workflow/scripts')!r})\n"
        "from industry_adapter import industry_mode\n"
        f"config = {{'foresight': 'overnight', 'heat_coupling': False, "
        f"'scenario': {{'planning_horizons': [2030]}}, 'sectors': {{'industry': {{'mode': {mode!r}}}}}}}\n"
        f"RESULTS_DIR = {str(tmp_path / 'results')!r}\n"
        f"LOG_DIR = {str(tmp_path / 'logs')!r}\n"
        f"COSTS_DATA = {str(tmp_path / 'costs')!r}\n"
        f"DERIVED_COMMON = {str(tmp_path / 'derived')!r}\n"
        f"include: {str(ROOT / 'workflow/rules/postprocess.smk')!r}\n"
    )
    return snakefile


def run_snakemake(snakefile, *args):
    cache = snakefile.parent / "source-cache"
    cache.mkdir(exist_ok=True)
    return subprocess.run(
        [sys.executable, "-m", "snakemake", "--snakefile", str(snakefile),
         "--directory", str(snakefile.parent), "--runtime-source-cache-path", str(cache),
         "--nolock", *args],
        check=True, capture_output=True, text=True,
    )


@pytest.mark.parametrize("mode", ["off", "fixed_load", "endogenous"])
def test_report_rule_exists_only_for_endogenous_industry(tmp_path, mode):
    rules = run_snakemake(workflow_file(tmp_path, mode), "--list-rules").stdout.splitlines()
    assert "plot_network" in rules  # The production include was actually loaded.
    assert ("industry_report" in rules) == (mode == "endogenous")


def test_snakemake_exports_from_existing_solved_network(tmp_path):
    source = tmp_path / "results/postnetworks/ntwk_2030.nc"
    source.parent.mkdir(parents=True)
    solved_network().export_to_netcdf(source)
    target = tmp_path / "results/industry/ntwk_2030"
    run_snakemake(workflow_file(tmp_path, "endogenous"), str(target), "--cores", "1")
    assert pd.read_csv(target / "routes.csv").period_production_t.sum() == pytest.approx(12)
    assert pd.read_csv(target / "inventory.csv").capacity_t.sum() == pytest.approx(0)
    audit = json.loads((target / "audit.json").read_text())
    assert audit["period_hours"] == 6
    assert not audit["annual_result"]
    assert set(audit["tables"]) == {"routes", "inventory", "resources", "electricity_replacement"}
