---
name: read-vis
description: Check a paper's visual presentation for layout, figure quality, spacing, and formatting issues. Use when reviewing paper polish before submission.
author: PaperDoctor Research
license: MIT
argument-hint: paper.pdf
allowed-tools: Read, Bash(python *)
---

# Paper Visual Check

Check a paper from the visual side.

Focus on what can be seen on the page:
- layout is reasonable or not
- figures are too small or too large
- spacing is awkward
- tables are cramped or hard to read
- captions are detached
- figures look low-quality or obviously AI-generated

Do not focus on code, experiments, or citations here.

## When to Use

- Check whether the paper looks polished
- Find obvious visual problems before submission
- Review figures, tables, spacing, and page balance

## Workflow

```text
Visual Check:
- [ ] Resolve PDF input
- [ ] Reuse or render page images
- [ ] Inspect pages visually
- [ ] Save report
```

## Resolve Input

- Input should be a PDF path.
- If `prepare-paper` has already run, use `{paper_dir}/metadata/page/` as the page-image directory.
- If page images do not exist yet, render them with:

```bash
python tools/pdf_render.py /path/to/paper.pdf
```

This writes:

- `{paper_dir}/metadata/page/page-001.png`, `page-002.png`, ...
- `{paper_dir}/metadata/page/manifest.json`

## What to Check

Look for visible issues such as:

- bad spacing
- poor page balance
- overflow or clipping
- a weak last line with only a few trailing words
- tiny figures or tables
- figures that are too large for their value
- captions far from the figure or table
- crowded tables
- blurry or low-quality figures
- figures with obvious AI-generation artifacts

Every finding should point to a specific target when possible:

- `Figure 2`
- `Table 3`
- `right-column equation block`
- `bottom image on page 6`
- `caption under Figure 4`

Do not write vague findings like "layout is a bit off". Say exactly what is wrong and where it is.

Do not treat anonymous submission formatting as a visual issue.
Examples:

- `Anonymous Author(s)`
- hidden affiliations
- placeholder contact fields used for blind review

These are submission-state choices, not layout defects.

If a paragraph ends with a very short final line, treat that as a valid visual issue when it makes the page look poorly balanced. Suggest reflowing nearby text, adjusting spacing, or reordering content.

## Zoom in when in doubt

When a figure or table is too dense or too small to judge confidently from the full page, crop the region and re-read the crop:

```bash
python -c "
from PIL import Image
Image.open('{paper_dir}/metadata/page/page-004.png').crop((LEFT, TOP, RIGHT, BOTTOM)).save('/tmp/zoom.png')
"
```

Then `Read /tmp/zoom.png` to inspect axis labels, sub-panel text, or AI-generation artifacts at full resolution. Crop instead of hedging — replace "might be too small to read" or "looks blurry but unsure" with a decisive judgment after a closer look.

## Output

Write the report by issue, not by page.

Each issue should be one concrete visual problem:

```json
{
  "page": 4,
  "quote": ["Figure 3"],
  "status": "warning",
  "reason": "Figure 3 is too small to read comfortably, especially the axis labels.",
  "suggest": "Enlarge Figure 3 or simplify the panel so the labels remain legible."
}
```

Use:

- `page`: page number
- `quote`: array of affected targets (e.g. `["Figure 3"]` or `["Figure 4", "Figure 5"]`)
- `status`: `warning` or `error`
- `reason`: exact visual problem
- `suggest`: concrete suggestion

**`status` rules:**

- `error` — **100% certain defects**:
  - Content clipped/cut off, text completely illegible, broken layout
  - Missing figures, factual errors in figure content (wrong labels, copy-paste)
  - **Obviously AI-generated figures** with visible artifacts (extra fingers, garbled text, impossible geometry, hallucinated details) used as actual scientific content (not as decorative illustrations)

- `warning` — **genuine quality issues**:
  - Rough/unpolished figures that look hastily made (misaligned elements, inconsistent styling, low-resolution rasterized text)
  - Overlapping text that obscures data, color choices that make categories indistinguishable
  - Figures or tables that are **too sparse** — excessive whitespace, a tiny chart floating in a large empty area, a table with 2 rows taking half a page
  - Important labels hard to read even when zoomed in

**Do NOT flag (not even warning):**
- **Polished** dense figures with clean vector graphics, consistent styling, clear legends — density is a feature when well-executed
- Tables with small but readable font — standard in conference papers
- Pages with multiple well-formatted figures/tables — layout choice

**Quality judgment guide:**
- **Polished & informative** (clean vector graphics, consistent colors, clear legends, professional layout) → do not flag, even if dense
- **Rough & poorly executed** (default matplotlib with no styling, blurry/pixelated sub-images, misaligned labels, hard to compare panels, missing visual separators, low-resolution rasterized content, inconsistent fonts/sizing) → `warning`
- **AI-generated artifacts** (DALL-E/Midjourney figures with telltale distortions used as scientific figures) → `error`
- **Too sparse** (a bar chart with 3 bars taking an entire page, mostly empty figure area) → `warning`
- **Dense comparison grids** where sub-images are too small to see meaningful differences → `warning`

**Font size rule of thumb:** Compare text inside figures/tables to the paper's body text. If figure labels, axis text, or table content is **noticeably smaller than the body text** (roughly <60% of body font size), flag as `warning`. Body text in a standard conference paper is ~10pt; figure text below ~6pt is a problem.

**Figure-caption coherence:**
- A good figure makes its caption easy to understand — the visual clearly illustrates what the caption describes
- `warning` if a figure is hard to connect to its caption (e.g. caption describes a trend but the figure doesn't clearly show it, or caption references sub-panels by labels that are missing/hard to find)
- `error` if the caption describes something completely different from what the figure shows (factual mismatch)

Aim for quality over quantity — fewer, more actionable findings are better than many nitpicks.

Save one report with:

- `summary`
- `issues`

Example shape:

```json
{
  "summary": {
    "total_issues": 5,
    "warning_issues": 4,
    "error_issues": 1
  },
  "results": [
    {
      "page": 4,
      "quote": ["Figure 3"],
      "status": "warning",
      "reason": "Figure 3 is too small to read comfortably, especially the axis labels.",
      "suggest": "Enlarge Figure 3 or simplify the panel so the labels remain legible."
    }
  ]
}
```

If a page has no visual problem, do not create a dummy entry for that page.

Output:

- `{paper_dir}/reports/check_vis.json`

## Tips

- Judge from visual evidence only.
- Prefer obvious, actionable feedback.
- If a figure looks AI-generated, say what visual artifact suggests that.
