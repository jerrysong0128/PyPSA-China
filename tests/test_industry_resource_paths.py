"""Keep local industry inputs distinct from reused PIK energy resources."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "industry_resource_paths_runner", ROOT / "scripts/industry_validation/run_pik_validation.py"
)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def test_reused_resources_do_not_redirect_local_industry_inputs(tmp_path):
    config = {
        "load": "resources/data/load/input.csv",
        "industry": [
            "resources/data/industry/sources/manifest.json",
            "resources/derived_data/industry/validation/steel_routes_2030.yaml",
        ],
        "explicit": "/another/explicit/input.csv",
    }
    mapped = runner.source_paths(config, tmp_path)
    assert mapped["load"] == str(tmp_path / config["load"])
    assert mapped["industry"] == [str(ROOT / value) for value in config["industry"]]
    assert mapped["explicit"] == config["explicit"]
