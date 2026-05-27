---
name: prepare-paper
description: Organize a paper PDF and its codebase into clean reading artifacts. Use this before any other read-* skills.
author: PaperDoctor Research
license: MIT
argument-hint: paper.pdf
allowed-tools: Read, Bash(python *), Bash(kill *)
---

# Prepare Paper

 Use this workflow to organize a paper PDF and code into clean reading artifacts.
 
## Overall Flow

```text
  +---------------------------+    +---------------------------+    +---------------------------+
  | Step 1: Parse PDF         |    | Step 2: Render Pages     |    | Step 3: Index Codebase   |
  | api_mathpix.py            |    | render page PNGs         |    | build code index         |
  +---------------------------+    +---------------------------+    +---------------------------+
               \                           |                           /
                \                          |                          /
                 \_________________________|_________________________/
                                            |
                                            v
                           +---------------------------+
                           | Step 4: Organize Paper   |
                           | full.md / refs / sections|
                           +---------------------------+
```

Parallel rule:
- Step 1, Step 2, and Step 3 run in **parallel**.
- Step 4 runs only after all three parallel steps finish.
- Treat Step 4 as the synchronization point after the parallel phase.

## Four Steps

### Step 1: Parse the PDF with Mathpix

**Prefer `api_mathpix.py` (Mathpix API) first** — it produces high-quality markdown with LaTeX math and downloads images locally.

Primary command (try first):

```bash
python tools/api_mathpix.py papers/<paper_dir>/<paper_file>.pdf
```

This uploads the PDF, waits for processing, downloads markdown + images to `papers/<paper_dir>/metadata/<arxiv_id>/mathpix/`.

Fallback (only if Mathpix API fails — account disabled, network error, etc.):

```bash
python tools/api_mineru.py -p papers/<paper_dir>/<paper_file>.pdf -o papers/<paper_dir>/metadata
```

### Step 2: Render page images

Command:

```bash
python tools/pdf_render.py papers/<paper_dir>/<paper_file>.pdf
```

### Step 3: Index the codebase

Command:

```bash
python tools/code_analyzer.py papers/<paper_dir>/<repo_dir> --output papers/<paper_dir>/metadata/code/index.json
```

### Step 4: Organize the paper markdown

Command:

```bash
python tools/organize_paper.py --paper-file papers/<paper_dir>/<paper_file>.pdf
```

This step reads the Mathpix/MinerU output from Step 1 and writes the normalized paper text, extracted references, and per-section markdown files.

## Execution Order

Run the workflow like this:

1. Start Step 1, Step 2, and Step 3 in parallel when needed.
2. Wait for all of Step 1, Step 2, and Step 3 to finish.
3. Run Step 4.

## Common Issues

- **Always try `python tools/api_mathpix.py` first.** Only fall back to `api_mineru.py` if the Mathpix API fails.
- Paper text is read from `{paper_dir}/metadata/{arxiv_id}/mathpix/{arxiv_id}.md` by downstream skills.
- Run `organize_paper.py` only after Mathpix/MinerU output exists.
- If Step 4 fails, first check whether markdown actually exists under `metadata/<pdf_stem>/`.
