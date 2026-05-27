#!/usr/bin/env python3
"""Search for quote strings in a PDF and return their page numbers and bounding boxes.

Uses PyMuPDF (fitz) for text search.

Usage:
    python tools/pdf_search.py paper.pdf quotes.json
    python tools/pdf_search.py paper.pdf --quote "some text to find"

Input quotes.json format:
    [
      {"id": "1", "quote": "exact sentence from the paper", "status": "warning"},
      {"id": "vis-3", "quote": ["Figure 4", "Figure 5"], "status": "error"}
    ]

Output (stdout as JSON):
    [
      {
        "id": "1",
        "quote": "exact sentence from the paper",
        "status": "warning",
        "matches": [
          {"page": 3, "bbox": [x0, y0, x1, y1]}
        ]
      },
      ...
    ]

Each bbox is in PDF points (72 dpi) relative to the page origin (top-left).
If a quote is not found, matches is an empty list.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import fitz  # PyMuPDF


# LaTeX inline math: $...$ (no nested $)
_LATEX_MATH = re.compile(r'\$[^$]*\$')
# LaTeX commands like \mathcal, \mathrm{T}, \emph{x}, optionally with [opt] and {arg}*
_LATEX_CMD = re.compile(r'\\[a-zA-Z]+\*?(\[[^\]]*\])?(\{[^}]*\})*')
# LaTeX escaped punctuation: \%  \&  \_  \#  \$
_LATEX_ESC = re.compile(r'\\([%&_#$])')
# Unicode punctuation that's commonly mismatched against PDFs
_PUNCT_MAP = {
    '‘': "'", '’': "'",
    '“': '"', '”': '"',
    '–': '-', '—': '-',
    ' ': ' ',
}
_WS = re.compile(r'\s+')


def _clean(text: str) -> str:
    """Strip LaTeX markup and normalize punctuation/whitespace."""
    if not text:
        return ''
    t = _LATEX_MATH.sub(' ', text)
    t = _LATEX_CMD.sub(' ', t)
    t = _LATEX_ESC.sub(r'\1', t)
    for k, v in _PUNCT_MAP.items():
        t = t.replace(k, v)
    return _WS.sub(' ', t).strip()


def _apostrophe_variants(s: str) -> list[str]:
    """Variants swapping straight ↔ curly apostrophes (papers commonly use ’)."""
    out = [s]
    if "'" in s:
        out.append(s.replace("'", "’"))
    if "’" in s:
        out.append(s.replace("’", "'"))
    return out


def _times_sign_variants(s: str) -> list[str]:
    """Variants swapping `Nx` ↔ `N×` between digits (papers often use ×)."""
    out = [s]
    a = re.sub(r'(\d)x', r'\1×', s)
    if a != s: out.append(a)
    b = re.sub(r'(\d)×', r'\1x', s)
    if b != s: out.append(b)
    return out


def _underscore_variants(s: str) -> list[str]:
    """Variants for `A_T` (subscript) — PDF often renders as `AT`."""
    out = [s]
    if '_' in s:
        out.append(s.replace('_', ''))
    return out


def _candidates(term: str) -> list[str]:
    """Generate progressively-fuzzier search candidates for a quote.

    Order: original → cleaned full → punctuation/sign variants → leading
    whitespace-split tokens (with the same variants). The first candidate
    that matches anywhere in the PDF wins.
    """
    if not term or len(term) < 3:
        return []
    seen: set[str] = set()
    out: list[str] = []

    def add(s: str, min_len: int = 6) -> None:
        s = (s or '').strip().rstrip(',.;:!?')
        if s and len(s) >= min_len and s not in seen:
            seen.add(s)
            out.append(s)

    def add_variants(s: str, min_len: int = 6) -> None:
        if not s:
            return
        for v1 in _apostrophe_variants(s):
            for v2 in _times_sign_variants(v1):
                for v3 in _underscore_variants(v2):
                    add(v3[:80], min_len=min_len)

    # 1. Original (truncated to 80) + punctuation variants.
    add_variants(term[:80])
    # 2. Cleaned (LaTeX-stripped) full + truncations + variants.
    cleaned = _clean(term)
    if cleaned and cleaned != term:
        add_variants(cleaned[:80])
        add_variants(cleaned[:40])
    # 3. Leading-token prefixes — the most reliable fallback for
    #    paraphrased tails, line wraps, and table-cell strings. Tokens are
    #    stripped of edge punctuation so that "salience:" → "salience".
    raw_tokens = (cleaned or term).split()
    tokens = [t.strip('.,;:!?()[]{}"\'') for t in raw_tokens]
    tokens = [t for t in tokens if t]
    for n in (5, 4, 3, 2):
        if len(tokens) >= n:
            add_variants(' '.join(tokens[:n]), min_len=8)
    return out


_STOPWORDS = {
    'the', 'a', 'an', 'is', 'of', 'to', 'and', 'or', 'in', 'on', 'at',
    'by', 'for', 'with', 'as', 'than', 'that', 'this', 'these', 'those',
    'we', 'our', 'are', 'be', 'it', 'its', 'their', 'from', 'into', 'but',
}


def _distinctive_tokens(text: str) -> list[str]:
    """Distinctive non-stopword tokens (≥3 chars) for row-cluster expansion."""
    tokens: list[str] = []
    for t in text.split():
        t = t.strip('.,;:!?()[]{}"\'')
        if not t or len(t) < 3:
            continue
        if t.lower() in _STOPWORDS:
            continue
        if not re.search(r'[A-Za-z0-9]', t):
            continue
        if t not in tokens:
            tokens.append(t)
    return tokens


def _column_id(page_width: float, rect: fitz.Rect) -> str:
    """Coarse column bucket for avoiding accidental two-column unions."""
    center = (rect.x0 + rect.x1) / 2
    # Full-width title/abstract/table regions legitimately cross the page
    # midpoint; treat them as compatible with either side.
    if rect.x0 < page_width * 0.42 and rect.x1 > page_width * 0.58:
        return "full"
    return "left" if center < page_width / 2 else "right"


def _same_column(page_width: float, a: fitz.Rect, b: fitz.Rect) -> bool:
    ca = _column_id(page_width, a)
    cb = _column_id(page_width, b)
    return ca == "full" or cb == "full" or ca == cb


def _rect_bbox(rects) -> fitz.Rect:
    """Union a group of search fragments into one rectangle."""
    x0 = min(r.x0 for r in rects)
    y0 = min(r.y0 for r in rects)
    x1 = max(r.x1 for r in rects)
    y1 = max(r.y1 for r in rects)
    return fitz.Rect(x0, y0, x1, y1)


def _visible_bbox(rect: fitz.Rect, page: fitz.Page) -> list[float]:
    """Return a bbox padded enough to remain visible under its number badge."""
    r = fitz.Rect(rect)
    # Tiny exact matches like "Figure 1" are technically correct, but the
    # numbered badge can visually cover the whole rectangle. Keep a modest
    # minimum footprint so every numbered match has a visible highlight region.
    min_w = 42.0
    min_h = 12.0
    pad = 1.2
    r.x0 -= pad
    r.y0 -= pad
    r.x1 += pad
    r.y1 += pad
    if r.width < min_w:
        d = (min_w - r.width) / 2
        r.x0 -= d
        r.x1 += d
    if r.height < min_h:
        d = (min_h - r.height) / 2
        r.y0 -= d
        r.y1 += d

    page_rect = page.rect
    if r.x0 < page_rect.x0:
        r.x1 += page_rect.x0 - r.x0
        r.x0 = page_rect.x0
    if r.x1 > page_rect.x1:
        r.x0 -= r.x1 - page_rect.x1
        r.x1 = page_rect.x1
    if r.y0 < page_rect.y0:
        r.y1 += page_rect.y0 - r.y0
        r.y0 = page_rect.y0
    if r.y1 > page_rect.y1:
        r.y0 -= r.y1 - page_rect.y1
        r.y1 = page_rect.y1

    r.x0 = max(page_rect.x0, r.x0)
    r.y0 = max(page_rect.y0, r.y0)
    r.x1 = min(page_rect.x1, r.x1)
    r.y1 = min(page_rect.y1, r.y1)
    return [round(r.x0, 1), round(r.y0, 1), round(r.x1, 1), round(r.y1, 1)]


def _make_match(page: fitz.Page, page_num: int, rect: fitz.Rect,
                term: str, candidate) -> dict:
    """Build a match dict — uniform shape used by every search path."""
    return {
        "page": page_num,
        "bbox": _visible_bbox(rect, page),
        "term": term,
        "candidate": candidate,
        "page_width": round(page.rect.width, 1),
        "page_height": round(page.rect.height, 1),
    }


def _refine_with_row_cluster(doc, term: str, literal_matches: list[dict],
                              y_tol: float = 14.0,
                              min_extra_hits: int = 3) -> list[dict]:
    """For table-row quotes, the literal candidate may anchor on a single
    cell (e.g. "w/o salience") even though the agent's full quote also
    names siblings on the same row ("SST2 94.3, MNLI 84.7"). Expand each
    literal match's bbox to include other distinctive tokens that
    co-occur on the same y-band of the same page.
    """
    if not literal_matches:
        return literal_matches
    cleaned = _clean(term)
    distinctive = _distinctive_tokens(cleaned or term)
    if len(distinctive) < min_extra_hits + 1:
        return literal_matches  # Not enough other tokens to form a row.
    refined = []
    for m in literal_matches:
        page = doc[m['page'] - 1]
        b = m['bbox']
        anchor_rect = fitz.Rect(*b)
        page_width = page.rect.width
        anchor_cy = (b[1] + b[3]) / 2
        cluster = [anchor_rect]
        for tok in distinctive:
            for r in page.search_for(tok):
                if (
                    abs((r.y0 + r.y1) / 2 - anchor_cy) <= y_tol
                    and _same_column(page_width, anchor_rect, r)
                ):
                    cluster.append(r)
        if len(cluster) >= min_extra_hits + 1:
            refined.append(_make_match(page, m['page'], _rect_bbox(cluster),
                                       m.get('term', term), m.get('candidate')))
        else:
            refined.append(m)
    return refined


def _multi_token_match(doc, term: str, min_hits: int = 3, y_tol: float = 14.0) -> list[dict] | None:
    """Last-resort fallback for synthesized table-row quotes that don't
    exist as contiguous text in the PDF (e.g. ``APT: MNLI 86.4, SST2 94.5,
    SQuAD v2 81.8, Train Time 592.1%, ...``).

    Strategy: tokenize the quote into distinctive non-stopwords, find the
    page where the most of them appear, then **cluster those token rects
    by y-coordinate** to find the densest horizontal band — the row of the
    table where the values live. The bbox spans that band.
    """
    tokens = _distinctive_tokens(_clean(term) or term)
    if len(tokens) < min_hits:
        return None
    top = sorted(tokens, key=lambda x: -len(x))[:10]

    # Step 1 — pick the page on which the most distinctive tokens occur,
    # collecting every rect for later clustering.
    best_page, best_count, best_rects = None, 0, []
    for page_num in range(len(doc)):
        page = doc[page_num]
        rects: list = []
        count = 0
        for tok in top:
            rs = page.search_for(tok)
            if rs:
                count += 1
                rects.extend(rs)
        if count > best_count:
            best_count, best_page, best_rects = count, page_num, rects
    if best_page is None or best_count < min_hits or not best_rects:
        return None

    # Step 2 — cluster rects by y-band and column. A "row" is a set of rects
    # whose vertical centers fall within ``y_tol`` of each other *and* live in
    # the same coarse page column. Without the column guard, two-column papers
    # produce giant left-to-right boxes when unrelated tokens share a baseline.
    rects_sorted = sorted(best_rects, key=lambda r: (r.y0 + r.y1) / 2)
    best_band: list = []
    i = 0
    while i < len(rects_sorted):
        anchor_rect = rects_sorted[i]
        anchor_y = (rects_sorted[i].y0 + rects_sorted[i].y1) / 2
        band = []
        j = i
        while j < len(rects_sorted):
            rect = rects_sorted[j]
            ry = (rect.y0 + rect.y1) / 2
            if ry - anchor_y <= y_tol:
                if _same_column(doc[best_page].rect.width, anchor_rect, rect):
                    band.append(rect)
                j += 1
            else:
                break
        if len(band) > len(best_band):
            best_band = band
        i += 1

    rect = _rect_bbox(best_band) if len(best_band) >= 2 else best_rects[0]
    return [_make_match(doc[best_page], best_page + 1, rect, term, None)]


def _cluster_line_fragments(rects: list[fitz.Rect], page_width: float) -> list[list[fitz.Rect]]:
    """Group PyMuPDF search fragments that belong to one wrapped occurrence.

    ``page.search_for`` returns one rectangle per line fragment when the query
    crosses a line break. The review UI needs one clickable region per quote,
    so adjacent fragments are merged while distant repeated occurrences remain
    separate groups.
    """
    if len(rects) <= 1:
        return [rects]
    heights = sorted(max(1.0, r.height) for r in rects)
    median_h = heights[len(heights) // 2]
    max_gap = max(18.0, median_h * 1.8)
    same_line_tol = max(3.0, median_h * 0.65)

    ordered = sorted(rects, key=lambda r: (r.y0, r.x0))
    groups: list[list[fitz.Rect]] = []
    cur: list[fitz.Rect] = [ordered[0]]
    last = ordered[0]

    for rect in ordered[1:]:
        last_cy = (last.y0 + last.y1) / 2
        cy = (rect.y0 + rect.y1) / 2
        same_col = _same_column(page_width, last, rect)
        same_line = abs(cy - last_cy) <= same_line_tol and same_col
        next_wrapped_line = 0 <= rect.y0 - last.y1 <= max_gap and same_col
        if same_line or next_wrapped_line:
            cur.append(rect)
        else:
            groups.append(cur)
            cur = [rect]
        last = rect
    groups.append(cur)
    return groups


def _matches_from_rects(
    page: fitz.Page,
    page_num: int,
    rects: list[fitz.Rect],
    term: str,
    candidate: str,
) -> list[dict]:
    if not rects:
        return []
    # Long quote searches often return one tiny rect per wrapped line. Merge
    # those fragments; leave short fallback candidates split to avoid merging
    # unrelated repeated common phrases into a giant highlight.
    should_merge = len(candidate) >= 30 and len(candidate.split()) >= 4
    groups = _cluster_line_fragments(rects, page.rect.width) if should_merge else [[r] for r in rects]
    return [_make_match(page, page_num, _rect_bbox(group), term, candidate) for group in groups]


def search_pdf(pdf_path: str, queries: list[dict]) -> list[dict]:
    """Search for each query's quote text in the PDF.

    Args:
        pdf_path: Path to the PDF file.
        queries: List of dicts with 'id', 'quote' (str or list[str]), and optional 'status'.

    Returns:
        List of dicts with 'id', 'quote', 'status', 'matches'.
    """
    doc = fitz.open(pdf_path)
    results = []

    for q in queries:
        qid = q.get("id", "")
        quote = q.get("quote", "")
        status = q.get("status", "warning")

        terms = quote if isinstance(quote, list) else [quote]

        matches = []
        for term in terms:
            term_matches = []
            for cand in _candidates(term):
                hits = []
                for page_num in range(len(doc)):
                    page = doc[page_num]
                    rects = page.search_for(cand)
                    hits.extend(_matches_from_rects(page, page_num + 1, rects, term, cand))
                if hits:
                    term_matches = hits
                    break  # Stop falling back to fuzzier candidates.
            # Refine: if literal match anchored on a small cell but the
            # quote names many siblings on the same row, expand to row.
            if term_matches:
                term_matches = _refine_with_row_cluster(doc, term, term_matches)
            # Last-resort: co-occurring distinctive tokens on a single page —
            # bounded by the densest horizontal band (the table row).
            if not term_matches:
                fallback = _multi_token_match(doc, term)
                if fallback:
                    term_matches = fallback
            matches.extend(term_matches)

        results.append({
            "id": qid,
            "quote": quote,
            "status": status,
            "matches": matches,
        })

    doc.close()
    return results


def main():
    parser = argparse.ArgumentParser(description="Search for quotes in a PDF.")
    parser.add_argument("pdf", help="Path to input PDF")
    parser.add_argument("quotes", nargs="?", help="Path to quotes JSON file")
    parser.add_argument("--quote", help="Single quote string to search")
    parser.add_argument("-o", "--output", help="Output JSON file (default: stdout)")
    args = parser.parse_args()

    if args.quote:
        queries = [{"id": "cli", "quote": args.quote, "status": "info"}]
    elif args.quotes:
        with open(args.quotes) as f:
            queries = json.load(f)
    else:
        parser.error("Provide either a quotes JSON file or --quote 'text'")

    results = search_pdf(args.pdf, queries)

    output = json.dumps(results, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(output)
        print(f"Wrote {len(results)} results to {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
