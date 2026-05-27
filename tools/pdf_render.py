#!/usr/bin/env python3
"""Render PDF pages to PNG images.

Prefers pdf2image/poppler, but falls back to PyMuPDF when poppler is absent.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from pdf2image import convert_from_path
except Exception:  # pragma: no cover - optional dependency path
    convert_from_path = None

def get_metadata_page_dir(pdf_path: Path) -> Path:
    return pdf_path.parent / "metadata" / "page"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render PDF pages to PNG images.")
    parser.add_argument("pdf", help="Path to input PDF")
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory for rendered page images (default: <paper_dir>/metadata/page)",
    )
    parser.add_argument("--dpi", type=int, default=200, help="Render DPI (default: 200)")
    return parser.parse_args()


def _render_with_pdf2image(pdf_path: Path, out_dir: Path, dpi: int) -> list[dict[str, object]]:
    if convert_from_path is None:
        raise RuntimeError("pdf2image is not available")

    pages: list[dict[str, object]] = []
    images = convert_from_path(str(pdf_path), dpi=dpi)
    for index, img in enumerate(images, start=1):
        image_name = f"page-{index:03d}.png"
        image_path = out_dir / image_name
        img.save(str(image_path), "PNG")
        pages.append(
            {
                "page": index,
                "image_path": str(image_path),
                "width": img.width,
                "height": img.height,
            }
        )
    return pages


def _render_with_fitz(pdf_path: Path, out_dir: Path, dpi: int) -> list[dict[str, object]]:
    import fitz

    pages: list[dict[str, object]] = []
    doc = fitz.open(str(pdf_path))
    try:
        scale = dpi / 72.0
        matrix = fitz.Matrix(scale, scale)
        for index, page in enumerate(doc, start=1):
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            image_name = f"page-{index:03d}.png"
            image_path = out_dir / image_name
            pix.save(str(image_path))
            pages.append(
                {
                    "page": index,
                    "image_path": str(image_path),
                    "width": pix.width,
                    "height": pix.height,
                }
            )
    finally:
        doc.close()
    return pages


def render_pdf_pages(pdf: str | Path, output_dir: str | Path | None = None, dpi: int = 200) -> dict[str, object]:
    pdf_path = Path(pdf).expanduser().resolve()
    if not pdf_path.exists():
        raise FileNotFoundError(f"Input PDF not found: {pdf_path}")

    out_dir = (
        Path(output_dir).expanduser().resolve()
        if output_dir
        else get_metadata_page_dir(pdf_path)
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    renderer = "pdf2image"
    try:
        pages = _render_with_pdf2image(pdf_path, out_dir, dpi)
    except Exception:
        pages = _render_with_fitz(pdf_path, out_dir, dpi)
        renderer = "fitz"

    manifest: dict[str, object] = {
        "pdf": str(pdf_path),
        "dpi": dpi,
        "renderer": renderer,
        "pages": pages,
    }

    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {
        "output_dir": str(out_dir),
        "manifest_path": str(manifest_path),
        "pages": pages,
        "renderer": renderer,
    }


def main() -> int:
    args = parse_args()
    result = render_pdf_pages(args.pdf, args.output_dir, args.dpi)
    print(f"Rendered {len(result['pages'])} pages to {result['output_dir']}")
    print(f"Wrote {result['manifest_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
