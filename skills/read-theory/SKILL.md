---
name: read-theory
description: Verify theoretical claims — mathematical derivations, proofs, and formal arguments. Targets claims with evidence_type "theoretical" from check_claim.json.
author: PaperDoctor Research
license: MIT
argument-hint: [paper_dir]
allowed-tools: Read
---

# Verify Theory

Check each claim tagged `evidence_type: "theoretical"` by reading the paper's arguments and verifying them step by step.

## Workflow

```text
- [ ] Step 1: Load claims
- [ ] Step 2: Verify each argument
- [ ] Step 3: Save report
```

---

## Step 1: Load Claims

Read `{paper_dir}/reports/check_claim.json`. Filter to claims where `evidence_type` includes `"theoretical"`.

Each claim's `id`, `source`, `quote`, `claim`, `evidence_type` fields should be copied as-is into the output — do not modify them.

Read the full paper text from `{paper_dir}/metadata/{arxiv_id}/mathpix/{arxiv_id}.md`.

---

## Step 2: Verify Each Argument

For each theoretical claim, locate the relevant reasoning in the paper. Check:

- **Correctness** — does each step follow from the previous one? (algebraic, logical, or conceptual)
- **Assumptions** — are any implicit assumptions missing or unjustified?
- **Edge cases** — does the result hold at boundary conditions?
- **Notation consistency** — are symbols used consistently throughout?

For each claim, produce:

```json
{
  "id": 3,
  "source": "method",
  "quote": "Eqn. 4 → 6, Section 3.1\n\nBy substituting Eqn. 4 into Eqn. 5, we obtain the closed-form loss in Eqn. 6",
  "claim": "The soft-label loss simplifies to a closed-form KL divergence",
  "evidence_type": ["theoretical"],
  "status": "pass",
  "reason": ""
}
```

Field definitions (paper triple → fields):

| Field | When | Purpose |
|-------|------|---------|
| `quote` | always | The **Where** evidence. Start with where in the paper the argument lives (equation range, section, theorem), then a blank line, then the original sentence under scrutiny. |
| `reason` | warning/error only | The **Why**. What issue was found (e.g. "implicit assumption that distributions share support"). For `pass` you may include a one-line note about the verification work performed (e.g. "re-derived substitution from Eqn. 4 to 6"). |
| `suggest` | warning/error only | The **How**. One-sentence concrete fix the author can apply. |

Statuses:

| Status | Meaning |
|--------|---------|
| `pass` | Argument is correct |
| `warning` | Correct but has implicit assumptions, ambiguity, or missing edge-case discussion |
| `error` | Error found — wrong sign, dropped term, invalid logical step |

When `status` is `warning` or `error`, `reason` should explain the problem precisely and `suggest` should propose a concrete fix.

---

## Step 3: Save Report

Output: `{paper_dir}/reports/check_theory.json`

```json
{
  "summary": {
    "total": 3,
    "pass": 2,
    "warning": 1,
    "error": 0
  },
  "results": [
    {
      "id": 3,
      "source": "method",
      "quote": "Eqn. 4 → 6, Section 3.1\n\nBy substituting Eqn. 4 into Eqn. 5, we obtain the closed-form loss in Eqn. 6",
      "claim": "The soft-label loss simplifies to a closed-form KL divergence",
      "evidence_type": ["theoretical"],
      "status": "warning",
      "reason": "Re-derived substitution from Eqn. 4 to 6 — derivation assumes teacher and student distributions share the same support, but this is not stated.",
      "suggest": "State the shared-support assumption explicitly before Eqn. 4."
    }
  ]
}
```

## Coverage Rule

**Every claim with `theoretical` in evidence_type MUST appear in `results`. No claim may be silently skipped.** If a claim's theory is trivial or self-evident, still include it with `status: "pass"` and a brief note.

## Tips

- Reproduce each derivation from scratch — do not just skim the steps
- For math: pay attention to summation indices and what gets absorbed vs cancelled
- For non-math arguments: check if the logic actually supports the conclusion
- A missing qualifier is a `warning`, not an `error`
