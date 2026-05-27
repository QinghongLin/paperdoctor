#!/usr/bin/env python3
"""Prepare paper metadata from existing MinerU output.

Responsibilities:
- copy MinerU markdown into metadata/paper/full.md
- write metadata/paper/references.json
- write metadata/paper/sections/*.md

This script assumes MinerU has already been run:

    mineru -p <paper.pdf> -o <paper_dir>/metadata
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any


REFERENCE_HEADINGS = (
    "references",
    "reference",
    "bibliography",
    "works cited",
    "literature",
    "参考文献",
)


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text).strip("-")
    return text or "section"


def _is_heading(line: str) -> bool:
    return bool(re.match(r"^\s{0,3}#{1,6}\s+\S", line))


def _heading_text(line: str) -> str:
    return re.sub(r"^\s{0,3}#{1,6}\s+", "", line).strip().lower()


def _looks_like_reference_start(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    return bool(
        re.match(r"^(\[\d+\]|\d+\.\s|•\s|-?\s*[A-Z][^.]+?\(\d{4}[a-z]?\))", stripped)
    )


def _extract_reference_entries(ref_text: str) -> list[dict[str, Any]]:
    entries: list[str] = []
    current: list[str] = []

    for raw_line in ref_text.splitlines():
        line = raw_line.strip()
        if not line:
            if current:
                entries.append(" ".join(current).strip())
                current = []
            continue
        if _looks_like_reference_start(line) and current:
            entries.append(" ".join(current).strip())
            current = [line]
            continue
        current.append(line)

    if current:
        entries.append(" ".join(current).strip())

    parsed: list[dict[str, Any]] = []
    for idx, entry in enumerate(entries, start=1):
        year_match = re.search(r"\b(19|20)\d{2}[a-z]?\b", entry)
        parsed.append(
            {
                "id": f"ref-{idx:03d}",
                "year": year_match.group(0) if year_match else None,
                "raw_text": entry,
            }
        )
    return parsed


def extract_references_from_markdown(md_text: str) -> list[dict[str, Any]]:
    lines = md_text.splitlines()
    start_idx: int | None = None
    for idx, line in enumerate(lines):
        if _is_heading(line) and _heading_text(line) in REFERENCE_HEADINGS:
            start_idx = idx + 1
            break

    if start_idx is None:
        return []

    ref_lines: list[str] = []
    for line in lines[start_idx:]:
        if _is_heading(line):
            break
        ref_lines.append(line)

    return _extract_reference_entries("\n".join(ref_lines))


def _split_markdown_sections(md_text: str) -> list[dict[str, str]]:
    sections: list[dict[str, str]] = []
    current_title = "front-matter"
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_lines, current_title
        body = "\n".join(current_lines).strip()
        if body:
            sections.append({"title": current_title, "content": body + "\n"})
        current_lines = []

    for line in md_text.splitlines():
        if _is_heading(line):
            flush()
            current_title = re.sub(r"^\s{0,3}#{1,6}\s+", "", line).strip()
            current_lines.append(line)
        else:
            current_lines.append(line)

    flush()
    return sections


def _write_sections(sections_dir: Path, sections: list[dict[str, str]]) -> list[Path]:
    if sections_dir.exists():
        for existing in sections_dir.glob("*.md"):
            existing.unlink()
    sections_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for idx, section in enumerate(sections, start=1):
        slug = _slugify(section['title'])[:80]
        filename = f"{idx:02d}-{slug}.md"
        target = sections_dir / filename
        target.write_text(section["content"], encoding="utf-8")
        written.append(target)
    return written


def _find_mineru_markdown(paper_file: Path) -> Path:
    stem = paper_file.stem
    metadata_dir = paper_file.parent / "metadata"
    candidates = [
        metadata_dir / stem / "hybrid_auto" / f"{stem}.md",
        metadata_dir / stem / "auto" / f"{stem}.md",
        metadata_dir / f"{stem}.md",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    matches = sorted(metadata_dir.rglob(f"{stem}.md"))
    if matches:
        return matches[0]

    raise FileNotFoundError(
        "MinerU markdown output not found. Run: "
        f"mineru -p {paper_file} -o {metadata_dir}"
    )


def _prepare_from_pdf(paper_file: Path, force: bool = False) -> dict[str, Any]:
    mineru_md = _find_mineru_markdown(paper_file)
    metadata_paper_dir = paper_file.parent / "metadata" / "paper"
    full_md = metadata_paper_dir / "full.md"
    references_json = metadata_paper_dir / "references.json"
    sections_dir = metadata_paper_dir / "sections"

    metadata_paper_dir.mkdir(parents=True, exist_ok=True)
    if force or not full_md.exists():
        shutil.copyfile(mineru_md, full_md)

    md_text = full_md.read_text(encoding="utf-8")
    references = extract_references_from_markdown(md_text)
    _write_json(references_json, references)

    sections = _split_markdown_sections(md_text)
    written_sections = _write_sections(sections_dir, sections)

    return {
        "paper_file": str(paper_file),
        "mineru_markdown": str(mineru_md),
        "full_md": str(full_md),
        "sections_dir": str(sections_dir),
        "sections_count": len(written_sections),
        "references_file": str(references_json),
        "references_count": len(references),
    }


def _prepare_from_latex_dir(latex_dir: Path) -> dict[str, Any]:
    tex_files = sorted(latex_dir.glob("*.tex"))
    if not tex_files:
        raise FileNotFoundError(f"No .tex files found in {latex_dir}")

    main_tex = latex_dir / "main.tex"
    tex_path = main_tex if main_tex.exists() else max(tex_files, key=lambda p: p.stat().st_size)
    text = tex_path.read_text(encoding="utf-8", errors="ignore")

    md_text = re.sub(r"\\section\*?\{([^}]*)\}", r"# \1", text)
    md_text = re.sub(r"\\subsection\*?\{([^}]*)\}", r"## \1", md_text)
    md_text = re.sub(r"\\subsubsection\*?\{([^}]*)\}", r"### \1", md_text)

    metadata_paper_dir = latex_dir / "metadata" / "paper"
    full_md = metadata_paper_dir / "full.md"
    full_md.parent.mkdir(parents=True, exist_ok=True)
    full_md.write_text(md_text, encoding="utf-8")

    references: list[dict[str, Any]] = []
    bib_files = sorted(latex_dir.glob("*.bib"))
    if bib_files:
        raw_bib = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in bib_files)
        entries = re.split(r"(?=@\w+\{)", raw_bib)
        for idx, entry in enumerate(entries, start=1):
            entry = entry.strip()
            if not entry:
                continue
            year_match = re.search(r"year\s*=\s*[{\"]?((?:19|20)\d{2}[a-z]?)", entry, flags=re.I)
            references.append(
                {
                    "id": f"ref-{idx:03d}",
                    "year": year_match.group(1) if year_match else None,
                    "raw_text": entry,
                }
            )

    references_json = metadata_paper_dir / "references.json"
    _write_json(references_json, references)

    sections = _split_markdown_sections(md_text)
    written_sections = _write_sections(metadata_paper_dir / "sections", sections)

    return {
        "latex_dir": str(latex_dir),
        "full_md": str(full_md),
        "sections_dir": str(metadata_paper_dir / "sections"),
        "sections_count": len(written_sections),
        "references_file": str(references_json),
        "references_count": len(references),
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create metadata/paper/full.md, references.json, and sections/*.md."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--paper-file", type=Path, help="Path to a PDF whose MinerU output already exists.")
    group.add_argument("--latex-dir", type=Path, help="Path to a LaTeX source directory.")
    parser.add_argument("--force", action="store_true", help="Overwrite metadata/paper/full.md from MinerU.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    if args.paper_file:
        result = _prepare_from_pdf(args.paper_file.resolve(), force=args.force)
    else:
        result = _prepare_from_latex_dir(args.latex_dir.resolve())

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"full.md: {result['full_md']}")
        print(f"sections: {result['sections_count']} -> {result['sections_dir']}")
        print(f"references: {result['references_count']} -> {result['references_file']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise
