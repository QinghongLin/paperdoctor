---
name: read-bib
description: Verify each cited reference exists via web search.
allowed-tools: Read, WebSearch
---

Read the input `references.json`. For each entry, WebSearch its `raw_text` and record `found` or `not_found`.

Each entry's `id`, `year`, `raw_text` fields should be copied as-is into the output — do not modify them.

When status is `warning` or `error`, set `quote` to the URL(s) found during search (e.g. the correct arXiv/venue page) followed by a blank line and the original `raw_text` of the citation, so reviewers see both the candidate fix-up source and the original entry. Also include a `suggest` field with a concrete one-sentence fix the author can apply (e.g. "Update the year to 2025" or "Replace with the correct arXiv ID").

Input: `{paper_dir}/metadata/paper/references.json`
Output: `{paper_dir}/reports/check_bib.json`

```json
{
  "summary": { "total": 42, "pass": 38, "warning": 2, "error": 2 },
  "results": [
    { "id": "ref-001", "year": "2016", "raw_text": "[1] Jun Xu, Tao Mei, Ting Yao, and Yong Rui. Msr-vtt: A large video description dataset for bridging video and language. In CVPR, pages 5288–5296, 2016.", "status": "pass" },
    { "id": "ref-005", "year": "2020", "raw_text": "[5] ...", "status": "warning", "reason": "title found but venue/year differs", "quote": "https://arxiv.org/abs/...\n\n[5] ...", "suggest": "Update the year to 2021 to match the venue listing." },
    { "id": "ref-007", "year": "2017", "raw_text": "[7] ...", "status": "error", "reason": "not found or search returned no match", "quote": "[7] ...", "suggest": "Replace with a verified citation or remove the reference." }
  ]
}
```
