---
name: read-prior
description: Web-search validation of citation and novelty claims from check_claim.json. Checks whether cited facts are accurate and novelty claims ("first", "pioneering") hold against published literature.
author: PaperDoctor Research
license: MIT
tags: [Reference, Novelty, Citation-Check, WebSearch]
dependencies: [read-txt]
argument-hint: [paper_dir]
user-invocable: true
allowed-tools: Read, WebSearch, WebFetch
---

# Citation & Novelty Validation

Validate claims from `check_claim.json` that require external evidence.

## Prerequisites

- `{paper_dir}/reports/check_claim.json`

## Workflow

```
- [ ] Step 1: Load target claims
- [ ] Step 2: Search and judge each claim
- [ ] Step 3: Save report
```

---

## Step 1: Load Target Claims

Read `{paper_dir}/reports/check_claim.json`. Collect all claims where `evidence_type` includes `"related_work"`.

Each claim's `id`, `source`, `quote`, `claim`, `evidence_type` fields should be copied as-is into the output — do not modify them.

These cover three sub-types — use the `quote` and `claim` text to identify which:

- **Baseline comparison** — compares against another method ("outperforms X by Y%")
- **Cited fact** — characterizes or cites another paper ("X achieves Y on benchmark Z")
- **Novelty assertion** — claims priority over prior work ("first", "pioneering", "no prior work has")

---

## Step 2: Search and Judge

For each claim, run **WebSearch queries**. When a relevant paper is found, **fetch its full page** (arXiv abstract or PDF landing page) and look for specific supporting details — e.g., which table reports the result, which section describes the method, what numbers are shown. Include these details in `reason` (e.g., "Table 2 in [paper] reports X% on [benchmark] under the same setting").

Assign a status:

| Status | Meaning |
|---------|---------|
| `pass` | Web evidence confirms the claim |
| `warning` | Claim is imprecise, overstated, or has a missing citation |
| `error` | Claim is factually wrong or clear prior art exists |
| `unverifiable` | Insufficient web evidence |

For novelty claims, also note if the novelty is `novel`, `incremental`, or `prior_art_exists`.

When `status` is `warning` or `error`, include a `suggest` field with a one-sentence concrete fix (e.g., "Relabel as `incremental` and cite Chen et al. 2021").

---

## Step 3: Save Report

Output: `{paper_dir}/reports/check_prior.json`

```json
{
  "summary": {
    "total": 5,
    "pass": 3,
    "warning": 1,
    "error": 0,
    "unverifiable": 1
  },
  "results": [
    {
      "id": 12,
      "source": "introduction",
      "quote": "We are the first to apply mutual information maximization to knowledge distillation",
      "claim": "No prior work has used mutual information for knowledge distillation",
      "evidence_type": ["related_work"],
      "status": "warning",
      "reason": "Chen et al. (2021) proposed MI-based distillation for NLP; this paper's novelty is limited to the vision domain",
      "suggest": "Relabel the novelty as `incremental`, restrict the claim to the vision domain, and cite Chen et al. (2021)."
    }
  ]
}
```

## Coverage Rule

**Every claim with `related_work` in evidence_type MUST appear in `results`. No claim may be silently skipped.** If a claim's cited fact checks out quickly, still include it with `status: "pass"` and the source.

## Tips

- Max **3 searches per claim** — stop early if confident
- Do not penalize for missing citations published after the paper's submission date
- Do not fabricate URLs — only include URLs returned by WebSearch
