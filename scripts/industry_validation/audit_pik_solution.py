#!/usr/bin/env python3
"""Export transparent numerical checks for an already solved validation network."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

import pypsa

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "workflow/scripts"))
from industry_accounting import validate_industry_solution  # noqa: E402


def audit_solution(network_path, output):
    """Report raw residuals and source drift; steel tolerances are checked by the solver."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    n = pypsa.Network(network_path)
    if n.meta.get("pik_validation", {}).get("stage") != "solved":
        raise ValueError("Expected a successfully solved validation network")
    n.statistics().to_csv(output / "statistics.csv")
    balance = n.statistics.energy_balance()
    balance.to_csv(output / "energy_balance.csv")
    ac_buses = n.buses.index[n.buses.carrier.eq("AC")]
    prices = n.buses_t.marginal_price.loc[:, ac_buses].stack()
    sources = {}
    for key, item in n.meta.get("industry_loads", {}).get("sources", {}).items():
        path = Path(item["path"])
        current = sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        sources[key] = dict(path=str(path), recorded_sha256=item["sha256"],
                            current_sha256=current, matches=current == item["sha256"])
    vre = n.generators.carrier.isin(["solar", "onwind", "offwind"])
    gens = n.generators.index[vre]
    availability = n.get_switchable_as_dense("Generator", "p_max_pu")[gens]
    possible = availability.mul(n.generators.p_nom_opt[gens]).mul(n.snapshot_weightings.generators, axis=0).sum().sum()
    actual = n.generators_t.p[gens].mul(n.snapshot_weightings.generators, axis=0).sum().sum()
    report = {
        "objective": n.objective,
        "physical_hours": float(n.snapshot_weightings.stores.sum()),
        "weights": n.snapshot_weightings.sum().to_dict(),
        "energy_balance_by_bus_carrier": balance.groupby(level="bus_carrier").sum().to_dict(),
        "ac_price_distribution": prices.describe(percentiles=[.01, .5, .99]).to_dict(),
        "vre_curtailment_fraction": (possible - actual) / possible if possible else None,
        "global_constraints": json.loads(n.global_constraints.reset_index().to_json(orient="records")),
        "sources": sources,
        "industry_validation": validate_industry_solution(n) if n.meta.get("industry") else None,
        "interpretation": "Engineering integration check; short windows do not establish annual planning conclusions",
    }
    (output / "solution_audit.json").write_text(json.dumps(report, indent=2, default=str))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("network", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report = audit_solution(args.network, args.output_dir)
    print(json.dumps({"objective": report["objective"], "physical_hours": report["physical_hours"],
                      "sources_match": all(x["matches"] for x in report["sources"].values())}, indent=2))
