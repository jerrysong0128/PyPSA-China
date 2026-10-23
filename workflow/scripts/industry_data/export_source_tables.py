"""Export preserved Excel sheets to CSV without changing their cell values.

Run after adding/updating an Excel source in sources/manifest.json. CSVs retain
Excel column letters and an explicit _source_row, including title/header rows.
Formula cells use the workbook's cached values; the original XLSX is retained.
Only Python's standard library is required.
"""

import argparse
import csv
import hashlib
import json
import posixpath
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile

from industry_paths import DATA, SOURCE_TABLES

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def sheet_targets(archive):
    """Resolve workbook sheet names to their archive member paths."""
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationships = {
        r.get("Id"): r.get("Target")
        for r in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    }
    result = {}
    for sheet in workbook.find("m:sheets", NS):
        target = relationships[
            sheet.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        ]
        result[sheet.get("name")] = (
            target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
        )
    return result


def shared_strings(archive):
    """Read workbook shared strings with bounded XML memory use."""
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    strings = []
    # Streaming avoids materializing the 139 MB ownership shared-string XML.
    with archive.open("xl/sharedStrings.xml") as stream:
        parser = ET.iterparse(stream, events=("start", "end"))
        _, root = next(parser)
        for event, element in parser:
            if event == "end" and element.tag == "{" + NS["m"] + "}si":
                strings.append("".join(t.text or "" for t in element.findall(".//m:t", NS)))
                root.clear()
    return strings


def archive_rows(archive, target, strings):
    """Yield cached cell values with their original Excel row coordinates."""
    with archive.open(target) as stream:
        parser = ET.iterparse(stream, events=("start", "end"))
        for event, row in parser:
            if event != "end" or row.tag != "{" + NS["m"] + "}row":
                continue
            values = {}
            for cell in row.findall("m:c", NS):
                value = cell.find("m:v", NS)
                inline = cell.find("m:is", NS)
                text = (
                    value.text
                    if value is not None
                    else (
                        "".join(t.text or "" for t in inline.findall(".//m:t", NS))
                        if inline is not None
                        else ""
                    )
                )
                if cell.get("t") == "s":
                    text = strings[int(text)]
                values[re.sub(r"\d+", "", cell.get("r"))] = text or ""
            yield int(row.get("r")), values
            row.clear()


def xlsx_rows(path, sheet):
    """Read one original worksheet without Excel or pandas type coercion."""
    with ZipFile(path) as archive:
        yield from archive_rows(archive, sheet_targets(archive)[sheet], shared_strings(archive))


def sheet_rows(directory, sheet):
    """Read an exported sheet with its original Excel row/cell addresses."""
    with (Path(directory) / (sheet + ".csv")).open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            yield int(row.pop("_source_row")), row


def column_number(column):
    """Convert an Excel column label to its one-based index."""
    value = 0
    for letter in column:
        value = value * 26 + ord(letter) - ord("A") + 1
    return value


def column_name(number):
    """Convert a one-based column index to its Excel label."""
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(ord("A") + remainder) + result
    return result


def export_workbook(path, directory):
    """Export every original sheet while preserving markers and row addresses."""
    directory.mkdir(parents=True, exist_ok=True)
    with ZipFile(path) as archive:
        strings = shared_strings(archive)
        for sheet, target in sheet_targets(archive).items():
            # A temporary JSONL stream keeps large ownership sheets bounded in
            # memory while discovering their maximum populated column.
            temporary = directory / ".sheet-rows.jsonl"
            width = 0
            try:
                with temporary.open("w", encoding="utf-8") as stream:
                    for row_number, row in archive_rows(archive, target, strings):
                        width = max(width, max(map(column_number, row), default=0))
                        stream.write(json.dumps([row_number, row], ensure_ascii=False) + "\n")
                columns = [column_name(i) for i in range(1, width + 1)]
                # Excel sheet names cannot contain /, so their names are safe
                # filenames and source locators remain directly readable.
                with (directory / (sheet + ".csv")).open(
                    "w", newline="", encoding="utf-8"
                ) as output:
                    writer = csv.writer(output)
                    writer.writerow(["_source_row", *columns])
                    with temporary.open(encoding="utf-8") as stream:
                        for line in stream:
                            number, row = json.loads(line)
                            writer.writerow([number, *(row.get(c, "") for c in columns)])
            finally:
                temporary.unlink(missing_ok=True)


def file_record(path, directory):
    """Record a generated file relative to its generated-data directory."""
    return dict(
        path=str(path.relative_to(directory)),
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        bytes=path.stat().st_size,
    )


def export_sources(manifest_path, output, register=False):
    """Export registered workbooks without mutating source metadata during builds."""
    data = manifest_path.parent.parent
    manifest = json.loads(manifest_path.read_text())
    records = {}
    for source in manifest["sources"]:
        if not source.get("csv_export_directory"):
            continue
        path = data / source["original_path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]:
            raise ValueError("Updated workbook must be explicitly registered first: " + str(path))
        directory = output / source["csv_export_directory"]
        export_workbook(path, directory)
        records[source["source_id"]] = [
            file_record(p, output) for p in sorted(directory.glob("*.csv"))
        ]
        if register:
            source["csv_exports"] = records[source["source_id"]]
        elif records[source["source_id"]] != source["csv_exports"]:
            raise ValueError(
                "Worksheet exports differ from registered values: " + source["source_id"]
            )
        print(f"{source['source_id']}: {len(records[source['source_id']])} sheets", flush=True)
    (output / "manifest.json").write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n")
    if register:
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")


def main():
    """Support the workflow and an explicit source-intake registration command."""
    if "snakemake" in globals():
        context = globals()["snakemake"]
        from contextlib import redirect_stderr, redirect_stdout

        log = Path(context.log[0])
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("w") as stream, redirect_stdout(stream), redirect_stderr(stream):
            export_sources(Path(context.input.manifest), Path(context.output.tables))
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DATA / "sources/manifest.json")
    parser.add_argument("--output", type=Path, default=SOURCE_TABLES)
    parser.add_argument(
        "--register",
        action="store_true",
        help="Explicit source intake only: update expected worksheet checksums after reviewing the registered workbook",
    )
    args = parser.parse_args()
    export_sources(args.manifest, args.output, args.register)


if __name__ == "__main__":
    main()
