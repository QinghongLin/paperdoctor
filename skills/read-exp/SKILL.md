---
name: read-exp
description: Review experiment design and produce a prioritized reproduction plan. Targets claims with evidence_type "experiment" from check_claim.json. Output feeds into run-exp.
author: PaperDoctor Research
license: MIT
argument-hint: [paper_dir]
allowed-tools: Read, Grep, Glob
---

# Review Experiments

Review experiment design for fairness and rigor, then produce a prioritized plan for reproduction.

## Workflow

```text
- [ ] Step 1: Load claims and paper
- [ ] Step 2: Review experiment design
- [ ] Step 3: Plan reproduction
- [ ] Step 4: Save report
```

---

## Step 1: Load Claims and Paper

- `{paper_dir}/reports/check_claim.json` — filter claims with `evidence_type` including `"experiment"`

Each claim's `id`, `source`, `quote`, `claim`, `evidence_type` fields should be copied as-is into the output — do not modify them.

- Paper text from `{paper_dir}/metadata/{arxiv_id}/mathpix/{arxiv_id}.md`
- Repo `README.md` — for setup instructions, datasets, checkpoints, commands

---

## Step 2: Review Experiment Design

For each experiment claim, assess the design quality:

- **Fair comparison** — same training setting, same data splits, same evaluation protocol as baselines?
- **Ablation sufficiency** — are the key components isolated and tested?
- **Statistical rigor** — are results averaged over multiple runs? error bars or std reported?
- **Baseline selection** — are the baselines relevant and recent enough?
- **Cherry-picking risk** — are only favorable configurations shown, or is coverage broad?

Each design issue:

```json
{
  "id": 9,
  "source": "experiments",
  "quote": "Results are averaged over 5 independent runs",
  "claim": "Main results are averaged over 5 runs",
  "evidence_type": ["experiment"],
  "status": "warning",
  "reason": "No standard deviation or confidence interval reported despite claiming 5 runs",
  "suggest": "Add standard deviations or confidence intervals across the 5 runs in Table 2."
}
```

When `status` is `warning` or `error`, include a `suggest` field with a concrete one-sentence fix.

---

## Step 3: Plan Reproduction

Scan the repo for datasets and checkpoints. For each experiment claim, assign:

- `priority`: **high** (main results) / **medium** (secondary) / **low** (very expensive)
- `feasibility`: **ready** (can run easily) / **blocked** (missing data, needs training, or too expensive)
- `mode`: **eval** / **train** / **other**
- `command`: exact command to run
- `goal`: key metric(s) and target value(s) from the paper

Data/checkpoint availability:

- **provided** — already exists locally
- **downloadable** — public URL, < 1 GB
- **restricted** — registration required, or > 1 GB

---

## Step 4: Save Report

Output: `{paper_dir}/reports/check_exp.json`

```json
{
  "summary": {
    "total_claims": 10,
    "design_issues": 3,
    "experiments": 5,
    "high": 2, "medium": 2, "low": 1,
    "ready": 1, "blocked": 4
  },
  "results": [
    {
      "id": 9,
      "source": "experiments",
      "quote": "Results are averaged over 5 independent runs",
      "claim": "Main results are averaged over 5 runs",
      "evidence_type": ["experiment"],
      "status": "warning",
      "reason": "No standard deviation or confidence interval reported despite claiming 5 runs",
      "suggest": "Add standard deviations or confidence intervals across the 5 runs in Table 2."
    }
  ],
  "plan": [
    {
      "id": 4,
      "source": "experiments",
      "quote": "Our method achieves 76.5% top-1 accuracy on CIFAR-100",
      "claim": "Proposed distillation method reaches 76.5% on CIFAR-100",
      "evidence_type": ["experiment"],
      "priority": "high",
      "feasibility": "ready",
      "mode": "eval",
      "command": "python eval.py --config configs/cifar100_resnet32x4.yaml --ckpt checkpoints/best.pth",
      "goal": {"top1_acc": 76.5}
    }
  ],
}
```

## Coverage Rule

**Every claim with `experiment` in evidence_type MUST appear in either `results` or `plan`. No claim may be silently skipped.** If a claim is not worth a full review, still include it in `results` with `status: "pass"` and a brief reason.

## Tips

- Missing error bars on a table that claims "average over N trials" is a `warning`
- Comparing against a 3-year-old baseline when newer ones exist is a `warning`
- Using different training epochs or data for your method vs baselines is an `error`
