# SPDX-License-Identifier: MIT
"""Source intake -> worksheet exports -> evidence -> optional engineering inputs."""

import os
from scripts.industry_data.industry_paths import EVIDENCE_FILES, VALIDATION_FILES, source_inputs

INDUSTRY_MANIFEST = config.get("industry_data", {}).get(
    "source_manifest", "resources/data/industry/sources/manifest.json"
)
# Match project-root-relative paths supplied to the sector adapter while using
# PathManager's production/test shared-data location.
INDUSTRY_DERIVED = os.path.relpath(os.path.join(DERIVED_COMMON, "industry"))
INDUSTRY_HELPERS = "workflow/scripts/industry_data/industry_paths.py"


rule export_industry_source_tables:
    input:
        manifest=INDUSTRY_MANIFEST,
        sources=lambda wc: source_inputs(INDUSTRY_MANIFEST, workbooks_only=True),
        helpers=INDUSTRY_HELPERS,
    output:
        tables=directory(INDUSTRY_DERIVED + "/source_tables"),
    log:
        LOGS_COMMON + "/industry/export_source_tables.log",
    threads: 1
    resources:
        mem_mb=2000,
    script:
        "../scripts/industry_data/export_source_tables.py"


rule build_industry_inputs:
    input:
        manifest=INDUSTRY_MANIFEST,
        sources=lambda wc: source_inputs(INDUSTRY_MANIFEST),
        tables=INDUSTRY_DERIVED + "/source_tables",
        provinces="resources/data/regions/province_codes.csv",
        helpers=[INDUSTRY_HELPERS, "workflow/scripts/industry_data/export_source_tables.py"],
    output:
        expand(INDUSTRY_DERIVED + "/evidence/{name}", name=EVIDENCE_FILES),
    log:
        LOGS_COMMON + "/industry/build_inputs.log",
    threads: 1
    resources:
        mem_mb=1000,
    script:
        "../scripts/industry_data/build_inputs.py"


# The annual load must be selected explicitly. Ordinary power/heat workflows
# acquire no industry-data dependency when this optional rule is unused.
if config.get("industry_data", {}).get("validation_load"):
    rule build_industry_validation:
        input:
            load=config["industry_data"]["validation_load"],
            assumptions=config["industry_data"].get(
                "validation_assumptions", "config/industry.validation_assumptions.yaml"
            ),
            evidence=expand(INDUSTRY_DERIVED + "/evidence/{name}", name=EVIDENCE_FILES),
            manifest=INDUSTRY_MANIFEST,
            helpers=[
                INDUSTRY_HELPERS,
                "workflow/scripts/industry_data/make_demo_inputs.py",
                "workflow/scripts/industry_model.py",
            ],
        output:
            expand(INDUSTRY_DERIVED + "/validation/{name}", name=VALIDATION_FILES),
        log:
            LOGS_COMMON + "/industry/build_validation.log",
        threads: 1
        resources:
            mem_mb=2000,
        script:
            "../scripts/industry_data/build_validation_bundle.py"
