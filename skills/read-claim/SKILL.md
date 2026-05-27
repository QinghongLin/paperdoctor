---
name: read-claim
description: Deep extraction of all verifiable claims from a research paper. Actively proposes implicit claims, splits compound statements, and flags cross-reference inconsistencies.
author: PaperDoctor Research
license: MIT
argument-hint: [paper_dir]
allowed-tools: Read, Glob
---

# Extract Claims

Extract all claims the authors make about their own work — both explicit and implicit. Actively look for hidden claims, split compound statements, and check cross-reference consistency.

## Workflow

```
- [ ] Step 1: Read full paper text
- [ ] Step 2: Extract explicit claims
- [ ] Step 3: Extract implicit claims
- [ ] Step 4: Split compound claims
- [ ] Step 5: Cross-reference check
- [ ] Step 6: Save report
```

## Step 1: Read Full Paper Text

```
Read {paper_dir}/metadata/{arxiv_id}/mathpix/{arxiv_id}.md
```

**Read the entire document — do not split by section.**

## Step 2: Extract Explicit Claims

A **claim** is any assertion the authors make about their own work that could in principle be validated.

**Not a claim**:
- Background statements ("Transformers have achieved success in NLP")
- Descriptions of other work ("As shown in [10], ...")
- Definitions ("We define ego-video as first-person footage")
- Writing quality issues (grammar, typos) — these belong in `read-txt`, not here

Each claim:

```json
{
  "id": 1,
  "source": "abstract",
  "quote": "exact sentence or phrase from the paper",
  "claim": "concise restatement of what is being asserted",
  "evidence_type": ["experiment"]
}
```

**`source`**: section where the claim appears (`abstract`, `introduction`, `method`, `experiments`, `conclusion`, `appendix`)

**`quote`**: exact original text — do not paraphrase

**`claim`**: clean one-sentence restatement of the assertion

**`evidence_type`** *(array — a claim may belong to multiple types)*:

| Value | Meaning |
|-------|---------|
| `experiment` | Should be validated by the paper's own experiments |
| `related_work` | Involves another paper — cited fact, baseline comparison, or novelty claim |
| `theoretical` | Supported by mathematical derivation or proof |
| `code` | Verifiable by inspecting the released code |

Every claim MUST map to at least one type. If unsure, apply this priority:

- Can it be checked by reading code/configs? → `code`
- Can it be checked against tables/figures? → `experiment`
- Is it a "should have done but didn't" ablation? → `experiment`
- Can it be checked against published literature? → `related_work`
- Is it a formal argument or derivation? → `theoretical`

**Hints for `related_work`**: assign when the claim cites or characterizes another paper, compares against a baseline, or asserts novelty ("first to", "pioneering"). Often combined with `experiment` when backed by the paper's own tables.

## Step 3: Extract Implicit Claims

Actively look for assertions that are **implied but not directly stated**:

### Numeric implications
- If abstract says "75.1% accuracy" and Table 2 also shows 75.1%, this implies "abstract matches Table 2" — extract as an `experiment` claim
- If a figure caption says "our method converges faster", extract the convergence claim

### Scope overclaims
- "effective" without qualifier → implies works in all settings
- "state-of-the-art" → implies tested against all relevant baselines
- "lightweight" → implies compared in model size / FLOPs
- "scalable" → implies tested at multiple scales
- Note what would be needed to fully support the claim in `implicit_reason`

### Method-result gaps
- Method section describes a component, but experiments don't ablate it → extract as: "Component X contributes to performance" (implicit, untested)
- A loss term is described but no ablation shows its effect → extract

### Comparative implications
- "outperforms X" → implies same evaluation protocol as X
- "with only 256K data" → implies others use more data (extract the comparison)
- "zero-shot" → implies no task-specific fine-tuning (verify definition matches standard usage)

```json
{
  "id": 33,
  "source": "experiments",
  "quote": "ShowUI achieves state-of-the-art grounding performance",
  "claim": "ShowUI outperforms all published methods on Screenspot grounding at time of submission",
  "evidence_type": ["experiment", "related_work"],
  "implicit_reason": "SOTA claim implies comparison against all relevant published baselines, but paper only compares against 5 methods"
}
```

## Step 4: Split Compound Claims

A single sentence often packs multiple independently verifiable assertions. **Always split** by the smallest verifiable unit:

- "We achieve 75.1% on ScreenSpot, 70.0% on AITW, and competitive results on Mind2Web" → **3 claims**
- "Our method is lightweight (2B) and uses less data (256K)" → **2 claims** (model size, data size)
- "Token selection reduces tokens by 33% and speeds up training by 1.4x" → **2 claims** (reduction rate, speedup)

Each sub-claim gets its own `id` and may have different `evidence_type`.

## Step 5: Cross-Reference Check

Scan for **internal consistency** issues between sections:

- Abstract numbers vs. table numbers — do they match exactly?
- Method description vs. code/config (if mentioned) — any discrepancy?
- Figures/tables referenced in text — do the cited values match what's shown?
- Contribution list in intro vs. what experiments actually validate

Extract these as claims with `evidence_type: ["experiment"]`:

```json
{
  "id": 45,
  "source": "abstract vs experiments",
  "quote": "75.1% accuracy in zero-shot screenshot grounding",
  "claim": "Abstract accuracy 75.1% matches Table 2 ShowUI row average",
  "evidence_type": ["experiment"]
}
```

## Step 6: Save Report

Output: `{paper_dir}/reports/check_claim.json`

```json
{
  "summary": {
    "total_claims": 50,
    "by_evidence_type": {
      "experiment": 25,
      "related_work": 10,
      "theoretical": 3,
      "code": 8
    }
  },
  "results": [
    {
      "id": 1,
      "source": "abstract",
      "quote": "exact text",
      "claim": "restatement",
      "evidence_type": ["experiment"]
    }
  ]
}
```

## Coverage Rule

**Err on the side of over-extraction** — downstream skills will filter. A missed claim cannot be verified later. Aim for 60+ claims on a typical 10-page paper.

## Tips

- Look for "we show", "we propose", "we achieve", "we demonstrate", "outperforms", "state-of-the-art", "first", "novel"
- Claims can appear anywhere — abstract, method, conclusion, captions, appendix
- Every number in the abstract should appear as a claim and be cross-referenced against the tables
- Passive voice often hides claims: "performance is improved by 3%" → who improved it? If the authors, it's a claim
- Qualifiers matter: "slightly better" vs "significantly better" vs "better" — extract the qualifier as part of the claim
- Figures are a rich source of implicit claims: trend lines, convergence curves, qualitative examples all assert something
- Do NOT flag writing issues (grammar, typos) — that is `read-txt`'s job
- **Ignore PDF parsing artifacts** in quotes: broken hyphens (`ex-\nploratory`), joined words from line breaks (`turnlevel`), LaTeX math (`$14.9 \%$`). Clean up the quote to match the actual paper text when extracting.
