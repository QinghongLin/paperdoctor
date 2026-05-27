#!/usr/bin/env python3
"""Merge all check_*.json into a unified review.json.

Uses check_claim.json as the master claim list, attaches verification verdicts
from each downstream skill, and includes standalone reports (vis, bib).

Usage:
    python tools/merge_reports.py papers/showui
"""

import argparse
import json
from pathlib import Path


def load_json(path):
    if path.exists():
        return json.loads(path.read_text())
    return None


def merge(paper_dir):
    reports = Path(paper_dir) / "reports"

    check_claim = load_json(reports / "check_claim.json")
    check_txt = load_json(reports / "check_txt.json")
    check_code = load_json(reports / "check_code.json")
    check_theory = load_json(reports / "check_theory.json")
    check_exp = load_json(reports / "check_exp.json")
    check_prior = load_json(reports / "check_prior.json")
    check_vis = load_json(reports / "check_vis.json")
    check_bib = load_json(reports / "check_bib.json")

    # ── Build verdict lookup: claim_id -> {skill: result_dict} ──
    def index_by_claim(report, skill_name):
        """Index a report's results by claim id."""
        out = {}
        if not report:
            return out
        for r in report.get("results", []):
            cid = r.get("id")
            if cid is not None:
                out[cid] = {
                    "skill": skill_name,
                    "status": r.get("status", ""),
                    "reason": r.get("reason", ""),
                    "reference": r.get("reference", ""),
                    "verify": r.get("verify", ""),
                }
        return out

    code_idx = index_by_claim(check_code, "code")
    theory_idx = index_by_claim(check_theory, "theory")
    exp_idx = index_by_claim(check_exp, "exp")
    prior_idx = index_by_claim(check_prior, "prior")

    # ── Severity ordering for overall status ──
    SEVERITY = {"error": 4, "warning": 3, "unverifiable": 2, "blocked": 1, "pass": 0, "": -1}

    def worst_status(statuses):
        """Return the most severe status."""
        best = ""
        for s in statuses:
            if SEVERITY.get(s, -1) > SEVERITY.get(best, -1):
                best = s
        return best or "pass"

    # ── Merge claims ──
    claims = []
    status_counts = {"pass": 0, "warning": 0, "error": 0, "unverifiable": 0, "blocked": 0}

    if check_claim:
        for item in check_claim.get("results", []):
            cid = item["id"]
            verdicts = {}

            for skill_name, idx in [("code", code_idx), ("theory", theory_idx),
                                     ("exp", exp_idx), ("prior", prior_idx)]:
                if cid in idx:
                    verdicts[skill_name] = idx[cid]

            statuses = [v["status"] for v in verdicts.values() if v["status"]]
            overall = worst_status(statuses) if statuses else "pending"

            if overall in status_counts:
                status_counts[overall] += 1

            claims.append({
                "id": cid,
                "source": item.get("source", ""),
                "quote": item.get("quote", ""),
                "claim": item.get("claim", ""),
                "evidence_type": item.get("evidence_type", []),
                "verdicts": verdicts,
                "overall": overall,
            })

    # ── Standalone reports (not tied to claims) ──
    standalone = {}

    if check_vis:
        vis_results = check_vis.get("results", [])
        standalone["vis"] = vis_results
        for r in vis_results:
            st = r.get("status", "")
            if st in status_counts:
                status_counts[st] += 1

    if check_bib:
        bib_results = check_bib.get("results", [])
        standalone["bib"] = bib_results
        for r in bib_results:
            st = r.get("status", "")
            if st in status_counts:
                status_counts[st] += 1

    if check_txt:
        txt_results = check_txt.get("results", [])
        standalone["txt"] = txt_results
        for r in txt_results:
            st = r.get("status", "")
            if st in status_counts:
                status_counts[st] += 1

    # ── Reproduction plan (from check_exp) ──
    plan = []
    if check_exp and "plan" in check_exp:
        plan = check_exp["plan"]

    # ── Assemble ──
    total = sum(status_counts.values())
    # Add pending claims (not yet verified by any skill)
    pending = sum(1 for c in claims if c["overall"] == "pending")

    review = {
        "summary": {
            "total_claims": len(claims),
            "total_findings": total,
            "pending": pending,
            "by_status": status_counts,
        },
        "claims": claims,
        "standalone": standalone,
        "plan": plan,
    }

    out_path = reports / "review.json"
    out_path.write_text(json.dumps(review, indent=2, ensure_ascii=False))
    return review, out_path


def main():
    parser = argparse.ArgumentParser(description="Merge check_*.json into review.json")
    parser.add_argument("paper_dir", help="Path to paper directory")
    args = parser.parse_args()

    review, out_path = merge(args.paper_dir)

    s = review["summary"]
    print(f"Wrote {out_path}")
    print(f"  Claims: {s['total_claims']} ({s['pending']} pending)")
    print(f"  Findings: {s['total_findings']}")
    counts = s["by_status"]
    parts = [f"{k}={v}" for k, v in counts.items() if v > 0]
    print(f"  Status: {', '.join(parts)}")


if __name__ == "__main__":
    main()
