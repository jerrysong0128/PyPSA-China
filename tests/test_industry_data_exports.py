"""Regression checks for sparse XLSX export and source-integrity dependencies."""

import hashlib
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "workflow/scripts/industry_data"))
try:
    import build_inputs
    from export_source_tables import export_workbook, sheet_rows
finally:
    sys.path.pop(0)


class SourceExportTests(unittest.TestCase):
    def test_sparse_cells_missing_markers_and_formula_cache(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            workbook = directory / "source.xlsx"
            with ZipFile(workbook, "w") as archive:
                archive.writestr(
                    "xl/workbook.xml",
                    """<workbook
                    xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
                    xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
                    <sheets><sheet name="Observations" sheetId="1" r:id="rId1"/></sheets></workbook>""",
                )
                archive.writestr(
                    "xl/_rels/workbook.xml.rels",
                    """<Relationships>
                    <Relationship Id="rId1" Target="/xl/worksheets/sheet1.xml"/>
                    </Relationships>""",
                )
                archive.writestr(
                    "xl/sharedStrings.xml",
                    """<sst
                    xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
                    <si><r><t>原始</t></r><r><t>标题</t></r></si></sst>""",
                )
                archive.writestr(
                    "xl/worksheets/sheet1.xml",
                    """<worksheet
                    xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
                    <row r="2"><c r="A2" t="s"><v>0</v></c></row>
                    <row r="7"><c r="A7"><v>-0.125</v></c>
                    <c r="C7" t="inlineStr"><is><t>N/A</t></is></c>
                    <c r="D7" t="inlineStr"><is><t>&gt;0</t></is></c>
                    <c r="AA7"><f>1+2</f><v>3</v></c></row>
                    </sheetData></worksheet>""",
                )
            export_workbook(workbook, directory / "csv")
            rows = list(sheet_rows(directory / "csv", "Observations"))
            self.assertEqual([n for n, _ in rows], [2, 7])
            self.assertEqual(rows[0][1]["A"], "原始标题")
            self.assertEqual(
                {k: rows[1][1][k] for k in ["A", "B", "C", "D", "AA"]},
                {"A": "-0.125", "B": "", "C": "N/A", "D": ">0", "AA": "3"},
            )
            self.assertEqual(len(rows[1][1]), 27)
            self.assertFalse((directory / "csv/.sheet-rows.jsonl").exists())

    def test_directory_and_csv_changes_fail_verification(self):
        with TemporaryDirectory() as temporary:
            data = Path(temporary)
            (data / "sources").mkdir()
            (data / "raw/repo").mkdir(parents=True)
            source = data / "raw/repo/model.gms"
            source.write_text("parameter p /1/;\n")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            fingerprint = hashlib.sha256(("model.gms\0" + digest + "\n").encode()).hexdigest()
            table = data / "raw/table.csv"
            table.write_text("_source_row,A\n1,N/A\n")
            manifest = {
                "sources": [
                    {
                        "original_path": None,
                        "repository_directory": "raw/repo",
                        "directory_fingerprint": {"files": 1, "sha256": fingerprint},
                    },
                    {
                        "original_path": None,
                        "additional_files": [
                            {
                                "path": "raw/table.csv",
                                "sha256": hashlib.sha256(table.read_bytes()).hexdigest(),
                            }
                        ],
                    },
                    {
                        "original_path": None,
                        "status": "reference_only",
                        "former_local_file": {"path": "raw/removed.pdf"},
                    },
                ]
            }
            (data / "sources/manifest.json").write_text(json.dumps(manifest))
            with patch.object(build_inputs, "DATA", data):
                build_inputs.verify_raw()
                source.unlink()
                with self.assertRaisesRegex(ValueError, "Source directory changed"):
                    build_inputs.verify_raw()
                source.write_text("parameter p /1/;\n")
                table.write_text("_source_row,A\n1,0\n")
                with self.assertRaisesRegex(ValueError, "Checksum mismatch"):
                    build_inputs.verify_raw()

    def test_download_does_not_export_unregistered_workbook_changes(self):
        with TemporaryDirectory() as temporary:
            data = Path(temporary)
            (data / "sources").mkdir()
            (data / "raw").mkdir()
            (data / "raw/source.xlsx").write_bytes(b"changed workbook")
            manifest = {
                "sources": [
                    {
                        "source_id": "example",
                        "original_path": "raw/source.xlsx",
                        "sha256": hashlib.sha256(b"expected workbook").hexdigest(),
                        "csv_export_directory": "raw/csv",
                        "csv_exports": [{"path": "raw/csv/Sheet.csv"}],
                    }
                ]
            }
            (data / "sources/manifest.json").write_text(json.dumps(manifest))
            with patch.object(build_inputs, "DATA", data):
                with self.assertRaisesRegex(ValueError, "Checksum mismatch"):
                    build_inputs.download()
            self.assertFalse((data / "raw/csv").exists())


if __name__ == "__main__":
    unittest.main()
