---
name: read-txt
description: Check writing quality — grammar, typos, unclear phrasing, inconsistent terminology, logical flow issues. Scans the full paper text and reports issues by page.
author: PaperDoctor Research
license: MIT
argument-hint: [paper_dir]
allowed-tools: Read, Glob
---

# Check Writing Quality

Scan the full paper text for writing issues: grammar errors, typos, unclear phrasing, inconsistent terminology, overclaim wording, and logical flow gaps.

## Workflow

```text
- [ ] Step 1: Read full paper text
- [ ] Step 2: Scan for writing issues
- [ ] Step 3: Save report
```

---

## Step 1: Read Full Paper Text

```
Read {paper_dir}/metadata/{arxiv_id}/mathpix/{arxiv_id}.md
```

**Read the entire document — do not split by section.**

---

## Step 2: Scan for Writing Issues

Scan every section for:

### Grammar
- Subject-verb disagreement ("this method can effectively balances")
- Wrong tense ("which we illustrated" when describing a figure → "illustrate")
- Missing articles ("available in community" → "in the community")
- Singular/plural mismatch ("three device" → "three devices")

### Typos & Formatting
- Misspelled words ("aling" → "allowing", "chocies" → "choices")
- Missing spaces ("inputsor" → "inputs or")
- Double brackets, broken formatting in tables/figures
- Wrong reference numbers

### Unclear Phrasing
- Vague language ("comparable results" without threshold)
- Awkward phrasing ("speeds up the performance")
- Incomplete sentences, missing objects ("surpasses in X" — surpasses what?)

### Inconsistent Terminology
- Same concept called different names in different sections
- Inconsistent capitalization of terms

### Overclaim Wording
- "significantly improves" without statistical test
- "universally effective" tested on only a few benchmarks
- "inherent property" from a single observation

### Logical Flow
- Conclusions not supported by the presented evidence
- Missing transitions between sections
- Claims in abstract/conclusion not backed by experiments

Each issue:

```json
{
  "page": 3,
  "quote": "this method can effectively balances component number",
  "status": "warning",
  "reason": "Subject-verb disagreement: 'can effectively balances' should be 'can effectively balance'.",
  "suggest": "Change 'balances' to 'balance'."
}
```

**`status`**:
- `warning` — grammar error, typo, unclear phrasing, minor inconsistency, or anything that MIGHT be a PDF parsing artifact
- `error` — **only for issues you are 100% certain exist in the actual paper**, not caused by PDF parsing. Examples: duplicated words ("that that"), wrong citation (citing paper A for paper B's result), clearly wrong terminology used consistently. If there is ANY chance the issue comes from PDF extraction, use `warning` instead

---

## Step 3: Save Report

Output: `{paper_dir}/reports/check_txt.json`

```json
{
  "summary": {
    "total_issues": 25,
    "warning_issues": 22,
    "error_issues": 3
  },
  "results": [
    {
      "page": 3,
      "quote": "this method can effectively balances component number",
      "status": "warning",
      "reason": "Subject-verb disagreement: 'can effectively balances' should be 'can effectively balance'.",
      "suggest": "Change 'balances' to 'balance'."
    }
  ]
}
```

## Tips

- Scan **every section** including abstract, appendix, table/figure captions, and references
- Non-native English writing often has systematic errors (e.g., missing articles throughout) — report the first 2-3 instances, then note "pattern continues throughout"
- Distinguish style preferences from actual errors — only flag clear mistakes or genuinely confusing phrasing
- Overclaim wording is `error` only if it misrepresents the actual results; stylistic exaggeration is `warning`

## Ignore PDF Parsing Artifacts

The input text is extracted from PDF via Mathpix/MinerU. **Do NOT flag these as writing issues:**

- **Broken hyphens**: `"ex-\nploratory"` or `"trajec-\ntory"` — these are line-break artifacts, not typos
- **Missing hyphens from line breaks**: `"turnlevel"` instead of `"turn-level"` — if the compound word clearly needs a hyphen but the text was joined across a line break, skip it
- **LaTeX math notation**: `$14.9 \%$`, `$\beta$`, `\mathbb{E}` — these are correct LaTeX, not formatting errors
- **Image references**: `![](images/img_001.jpg)` — skip these
- **Footnote markers**: `[^0]`, `${ }^{1}$` — PDF extraction artifacts
- **Garbled capitalization**: `"AgentFLOW"`, `"AgENTFlow"` — PDF extraction often mangles mixed-case words. Skip these entirely unless the same inconsistency appears multiple times in clearly different contexts
- **Grammar around LaTeX**: `"achieving average accuracy by $14.9 \%$"` — the awkwardness may come from LaTeX rendering, not the actual paper. If the sentence structure is otherwise sound, skip it

**Only flag issues that exist in the actual paper**, not artifacts from the PDF-to-markdown conversion. When in doubt, **downgrade to warning or skip entirely**.
