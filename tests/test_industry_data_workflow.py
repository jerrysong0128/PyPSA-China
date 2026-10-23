"""Exercise production data rules without downloading any external sources."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "workflow/scripts/industry_data"))
from industry_paths import source_inputs


def test_source_dependencies_include_nested_snapshot_files(tmp_path):
    manifest = tmp_path / "sources/manifest.json"
    manifest.parent.mkdir()
    source = tmp_path / "raw/repo/modules/industry.gms"
    source.parent.mkdir(parents=True)
    source.write_text("parameter p /1/;\n")
    manifest.write_text(json.dumps({"sources": [{"repository_directory": "raw/repo"}]}))
    assert str(source) in source_inputs(manifest)
    assert str(source.parent.parent) in source_inputs(manifest)
    assert source_inputs(manifest, workbooks_only=True) == [str(manifest)]


def test_production_export_rule_preserves_sources_and_rejects_changed_workbook(tmp_path):
    data = tmp_path / "data"
    manifest = data / "sources/manifest.json"
    manifest.parent.mkdir(parents=True)
    workbook = data / "raw/source.xlsx"
    workbook.parent.mkdir()
    with ZipFile(workbook, "w") as archive:
        archive.writestr(
            "xl/workbook.xml",
            """<workbook
            xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
            xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
            <sheets><sheet name="Values" sheetId="1" r:id="rId1"/></sheets></workbook>""",
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            """<Relationships>
            <Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>""",
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            """<worksheet
            xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
            <row r="1"><c r="A1" t="inlineStr"><is><t>N/A</t></is></c></row>
            </sheetData></worksheet>""",
        )
    expected = b"_source_row,A\r\n1,N/A\r\n"
    manifest.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "source_id": "synthetic",
                        "original_path": "raw/source.xlsx",
                        "sha256": hashlib.sha256(workbook.read_bytes()).hexdigest(),
                        "csv_export_directory": "synthetic",
                        "csv_exports": [
                            {
                                "path": "synthetic/Values.csv",
                                "bytes": len(expected),
                                "sha256": hashlib.sha256(expected).hexdigest(),
                            }
                        ],
                    }
                ]
            }
        )
    )
    before = manifest.read_bytes()
    snakefile = tmp_path / "Snakefile"
    snakefile.write_text(
        f"import sys\nsys.path.insert(0, {str(ROOT / 'workflow')!r})\n"
        f"config = {{'industry_data': {{'source_manifest': {str(manifest)!r}}}}}\n"
        f"DERIVED_COMMON = {str(tmp_path / 'derived')!r}\n"
        f"LOGS_COMMON = {str(tmp_path / 'logs')!r}\n"
        f"include: {str(ROOT / 'workflow/rules/industry_data.smk')!r}\n"
    )
    cache = tmp_path / "cache"
    cache.mkdir()
    command = [
        sys.executable,
        "-m",
        "snakemake",
        "--snakefile",
        str(snakefile),
        "--directory",
        str(ROOT),
        "--runtime-source-cache-path",
        str(cache),
        "--nolock",
        "--cores",
        "1",
        "export_industry_source_tables",
    ]
    subprocess.run(command, check=True, capture_output=True, text=True)
    exported = tmp_path / "derived/industry/source_tables/synthetic/Values.csv"
    assert exported.read_bytes() == expected
    assert manifest.read_bytes() == before
    assert (
        json.loads((exported.parent.parent / "manifest.json").read_text())["synthetic"][0]["sha256"]
        == hashlib.sha256(expected).hexdigest()
    )
    workbook.write_bytes(b"unregistered source change")
    failed = subprocess.run([*command, "--forceall"], capture_output=True, text=True)
    assert failed.returncode != 0
    assert "Updated workbook must be explicitly registered" in failed.stderr
    assert manifest.read_bytes() == before
