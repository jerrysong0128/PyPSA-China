"""Evidence checks independent of model implementation; no raw download needed."""

import csv
import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests/data/industry/evidence"


def rows(name):
    with (DATA / name).open() as f:
        return list(csv.DictReader(f))


class IndustryEvidenceTests(unittest.TestCase):
    def test_nbs_province_total_rounding_and_missing(self):
        data = rows("nbs_province_steel_production_2020.csv")
        self.assertEqual(len(data), 64)
        for var in ["crude_steel_production", "pig_iron_production"]:
            subset = [r for r in data if r["variable"] == var]
            national = next(Decimal(r["value"]) for r in subset if r["province"] == "China")
            total = sum(
                Decimal(r["value"]) for r in subset if r["province"] != "China" and r["value"]
            )
            self.assertLessEqual(abs(national - total), Decimal(100))
            for province in ["Beijing", "Hainan", "Tibet"]:
                r = next(r for r in subset if r["province"] == province)
                self.assertEqual(r["value"], "")
                self.assertEqual(r["missing_reason"], "blank_in_source_not_assumed_zero")

    def test_henan_nested_sectors_and_unit_conversion(self):
        data = {r["sector"]: Decimal(r["value"]) for r in rows("henan_sector_electricity_2024.csv")}
        self.assertEqual(data["total"], Decimal("431994000"))
        self.assertEqual(data["ferrous_smelting_rolling"], Decimal("13043000"))
        self.assertEqual(
            data["total"], sum(data[k] for k in ["primary", "secondary", "tertiary", "residential"])
        )
        self.assertLess(data["ferrous_smelting_rolling"], data["industry"])
        self.assertLess(data["industry"], data["secondary"])

    def test_capacity_status_and_production_are_separate(self):
        capacities = rows("gem_china_plant_capacity_2026.csv")
        self.assertEqual(len(capacities), 702)
        self.assertEqual(len({r["plant_id"] for r in capacities}), 458)
        self.assertEqual(len(capacities), len({r["source_row_id"] for r in capacities}))
        self.assertGreater(len({r["status"] for r in capacities}), 1)
        self.assertTrue(
            any(r["eaf_capacity_raw"] == "N/A" and r["eaf_capacity_tpy"] == "" for r in capacities)
        )
        self.assertTrue(
            any(r["eaf_capacity_raw"] == ">0" and r["eaf_capacity_tpy"] == "" for r in capacities)
        )
        self.assertEqual({r["reference_year"] for r in capacities}, {"2026"})
        production = rows("gem_china_plant_production_2019_2025.csv")
        self.assertEqual({r["year"] for r in production}, {str(y) for y in range(2019, 2026)})
        self.assertEqual(
            len(production), len({(r["source_id"], r["source_locator"]) for r in production})
        )
        repeated = [r for r in production if r["repeated_plant_year_product"] == "True"]
        self.assertEqual(len(repeated), 196)
        observed = [
            r
            for r in production
            if r["year"] == "2020" and r["variable"] == "crude_steel_production" and r["value"]
        ]
        self.assertEqual(len(observed), 36)
        self.assertEqual(len({r["plant_id"] for r in observed}), 35)
        self.assertEqual(sum(Decimal(r["value"]) for r in observed), Decimal("179824000"))
        # The source repeats Zhongpu's 2020 value; raw rows stay visible, and
        # this independent unique-plant check prevents calling their sum a total.
        unique = {(r["plant_id"], r["value"]) for r in observed}
        self.assertEqual(sum(Decimal(value) for _, value in unique), Decimal("177048000"))
        self.assertTrue(
            all(
                not r["value"]
                for r in production
                if r["year"] == "2025" and r["variable"] == "crude_steel_production"
            )
        )

    def test_gem_2026_capacity_units_and_routes(self):
        data = rows("gem_province_capacity_2026.csv")
        self.assertEqual(len(data), 140)
        total = sum(Decimal(r["value"]) for r in data if r["route"] == "total")
        self.assertEqual(total, Decimal("1088644000"))
        for province in {r["province"] for r in data}:
            d = {r["route"]: Decimal(r["value"]) for r in data if r["province"] == province}
            self.assertEqual(d["total"], sum(d[k] for k in ["BOF", "EAF", "IF", "other"]))

    def test_bachorz_process_units_and_yield(self):
        data = {
            (r["route"], r["parameter"]): Decimal(r["value"])
            for r in rows("bachorz_process_parameter_candidates.csv")
        }
        dri = data["DRI-EAF", "dri_t_per_tsteel"]
        electricity = (
            data["DRI-EAF", "electricity_mwh_per_tsteel"]
            + dri * data["H2-DRI", "electricity_mwh_per_tdri"]
        )
        self.assertEqual(electricity, Decimal("0.75520"))
        self.assertEqual(dri * data["H2-DRI", "hydrogen_lhv_mwh_per_tdri"], Decimal("2.37495"))

    def test_demo_missing_policy_and_adapter_schema(self):
        sys.path.insert(0, str(ROOT / "workflow/scripts/industry_data"))
        try:
            from make_demo_inputs import generate

            sectors, demand, capacity = generate({"Henan": 431994000.0}, 0.2, "fail", evidence=DATA)
            self.assertEqual({r["unit"] for r in sectors}, {"MWh"})
            self.assertEqual(demand[0]["unit"], "t")
            self.assertEqual(demand[0]["value"], 35301600.0)
            with self.assertRaisesRegex(ValueError, "explicit policy"):
                generate({"Beijing": 100000000.0}, 0.2, "fail", evidence=DATA)
            _, missing, _ = generate(
                {"Beijing": 100000000.0}, 0.2, "explicit_zero_scenario", evidence=DATA
            )
            self.assertEqual(missing[0]["value"], 0.0)
            self.assertIn("source_blank_explicit_zero", missing[0]["method"])
            with self.assertRaisesRegex(ValueError, "never clip"):
                generate({"Henan": 100.0}, 0.2, "fail", evidence=DATA)
            with self.assertRaises(ValueError):
                generate({"Henan": float("nan")}, 0.2, "fail", evidence=DATA)
        finally:
            sys.path.pop(0)

    def test_negative_net_electricity_not_clamped(self):
        r = next(
            r
            for r in rows("route_parameter_candidates.csv")
            if r["route"] == "BF-BOF" and r["parameter"] == "Electricity"
        )
        self.assertLess(Decimal(r["value"]), 0)
        self.assertEqual(r["readiness"], "candidate_requires_boundary_review")


if __name__ == "__main__":
    unittest.main()
