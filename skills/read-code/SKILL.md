---
name: read-code
description: Verify paper claims with evidence_type "code" against the actual codebase. Use after read-txt to check if code matches what the paper says.
author: PaperDoctor Research
license: MIT
argument-hint: [paper.pdf] [codebase-path]
allowed-tools: Read, Grep, Glob, Bash(python *)
---

# Verify Code Claims

Check each claim tagged `evidence_type: "code"` from read-txt against the actual codebase.

## Workflow

```text
Verify Code:
- [ ] Step 1: Load claims
- [ ] Step 2: Read code index
- [ ] Step 3: Verify each code claim
- [ ] Step 4: Save report
```

## Step 1: Load Claims

```
Read {paper_dir}/reports/check_claim.json
```

Filter to claims where `evidence_type` includes `"code"`. These are the claims to verify.

Each claim's `id`, `source`, `quote`, `claim`, `evidence_type` fields should be copied as-is into the output — do not modify them.

## Step 2: Read Code Index

```
Read {paper_dir}/metadata/code/index.json
```

This is the tree-sitter index from prepare-paper. Use it to locate relevant files, symbols, and config entries.

## Step 3: Verify Each Code Claim

For each code claim, find the relevant code and judge whether it matches.

**How to find code**: Use Grep, Glob, and the code index. For hyperparameters, check config files first. For architecture claims, check class definitions and `__init__` / `forward` methods.

For each claim, produce:

```json
{
  "id": 7,
  "source": "experiments",
  "quote": "model/encoder.py:42 — num_layers=12, hidden_size=768\n\nWe use a 12-layer transformer with embedding dimension 768",
  "claim": "Model architecture is a 12-layer, 768-dim transformer",
  "evidence_type": ["code"],
  "status": "pass",
  "reason": ""
}
```

Field definitions (paper triple → fields):

| Field | When | Purpose |
|-------|------|---------|
| `quote` | always | The **Where** evidence. **Must start with `path/to/file.ext:LINE` (or `:LINE-LINE`)** followed by `— short note about what the code shows`. If the issue is "feature X is missing from the repo", anchor to the most relevant file at line 0, e.g. `src/trainer/fgt_prediction_trainer.py:0 — no margin-loss entry point present`. After the file:line prefix you may include the original paper sentence on a new line so the reviewer sees both ends of the comparison. Downstream tooling extracts the `path:LINE` prefix to wire the code viewer. |
| `reason` | warning/error only | The **Why**. Explanation of the discrepancy. |
| `suggest` | warning/error only | The **How**. One-sentence concrete fix the author can apply. |

Statuses:

| Status | Meaning |
|---------|---------|
| `pass` | Code matches the claim |
| `warning` | Code is related but differs in detail (e.g., paper says Adam, code uses AdamW) |
| `error` | Code contradicts the claim, or no implementation found in the repo |

When `status` is `warning` or `error`, `reason` should explain the discrepancy and `suggest` should propose a concrete fix (e.g., "Update the paper text to match the code, or change the code to AdamW to match the paper claim").

## Step 4: Save Report

Output: `{paper_dir}/reports/check_code.json`

```json
{
  "summary": {
    "total": 8,
    "pass": 5,
    "warning": 2,
    "error": 1
  },
  "results": [
    {
      "id": 9,
      "source": "experiments",
      "quote": "configs/train.yaml:14 — optimizer: Adam\n\nWe train all models using the AdamW optimizer",
      "claim": "Training optimizer is AdamW",
      "evidence_type": ["code"],
      "status": "warning",
      "reason": "Paper says AdamW but configs/train.yaml line 14 sets optimizer: Adam",
      "suggest": "Update the paper text to AdamW or change the config to match the paper claim."
    },
    {
      "id": 10,
      "source": "method",
      "quote": "src/trainer/fgt_prediction_trainer.py:0 — no margin-loss entry point present\n\nWe use a custom margin-loss training objective",
      "claim": "Margin loss is the training objective",
      "evidence_type": ["code"],
      "status": "error",
      "reason": "No margin-loss entry point in src/trainer/; the released default uses binary cross-entropy.",
      "suggest": "Add the margin-loss entry point to the released code, or remove the claim from the paper."
    }
  ]
}
```

## Coverage Rule

**Every claim with `code` in evidence_type MUST appear in `results`. No claim may be silently skipped.** Valid statuses are `pass / warning / error`. If a claim cannot be verified at all from the codebase (no relevant file found, repo too incomplete), use `status: "warning"` with `quote` like `path/to/expected/file.ext:0 — file not in repo` so the reviewer can still see what was being checked.

## Tips

- Check config files (`.json`, `.yaml`) first — most hyperparameters live there, not in Python code
- Map paper terms to code terms (e.g., "learning rate" → `lr`, "layers" → `depth`)
- If the index has `config_entries`, search those before grepping full files
- A paper saying "Adam" when code uses "AdamW" is a `warning`, not an `error`
