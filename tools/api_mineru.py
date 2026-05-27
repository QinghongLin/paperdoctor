#!/usr/bin/env python3
"""MinerU API wrapper — drop-in replacement for the local `mineru` CLI.

Usage (matches local CLI):
    python tools/mineru_api.py -p papers/univtg/2307.16715v2.pdf -o papers/univtg/metadata

Output structure (same as local mineru):
    papers/univtg/metadata/2307.16715v2/auto/<pdf_stem>.md
    papers/univtg/metadata/2307.16715v2/auto/images/
    papers/univtg/metadata/2307.16715v2/auto/...
"""

import argparse
import pathlib
import shutil
import sys
import tempfile
import time
import zipfile
from io import BytesIO

import requests

# ---------------------------------------------------------------------------
# API token (hardcoded per user request)
# ---------------------------------------------------------------------------

TOKEN = (
    "eyJ0eXBlIjoiSldUIiwiYWxnIjoiSFM1MTIifQ"
    ".eyJqdGkiOiI0NDIwMDI3MCIsInJvbCI6IlJPTEVfUkVHSVNURVIiLCJpc3MiOiJPcGVuWExhYiIsImlhdCI6MTc3NTQyNzQxMiwiY2xpZW50SWQiOiJsa3pkeDU3bnZ5MjJqa3BxOXgydyIsInBob25lIjoiIiwib3BlbklkIjpudWxsLCJ1dWlkIjoiMTAzZTZkNGYtYjU3Ni00N2RlLWEwNTctMDdiMDZmZTE5Y2M1IiwiZW1haWwiOiIiLCJleHAiOjE3ODMyMDM0MTJ9"
    ".PfscODsuoIVITd6QzVukvOMf3__ULzCnq7xudKxax5NddRy64SATg4VWhQ9BfC7mzLSV7MJIv4jkeO9P4gSR1g"
)

BASE = "https://mineru.net/api/v4"
HEADERS = {"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"}


# ---------------------------------------------------------------------------
# Core API calls
# ---------------------------------------------------------------------------

def _upload_and_submit(pdf_path: pathlib.Path, **extract_kwargs) -> str:
    """Upload a local PDF and submit for extraction. Returns batch_id."""
    body = {"files": [{"name": pdf_path.name}]}
    for k in ("model_version", "is_ocr", "enable_formula", "enable_table",
              "language", "page_ranges"):
        if k in extract_kwargs and extract_kwargs[k] is not None:
            body[k] = extract_kwargs[k]

    resp = requests.post(f"{BASE}/file-urls/batch", headers=HEADERS, json=body)
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"Failed to get upload URL: {data}")

    batch_id = data["data"]["batch_id"]
    raw = data["data"]["file_urls"][0]
    upload_url = raw if isinstance(raw, str) else raw["url"]

    print(f"Uploading {pdf_path.name} ({pdf_path.stat().st_size / 1024 / 1024:.1f} MB) ...")
    with open(pdf_path, "rb") as f:
        r = requests.put(upload_url, data=f)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Upload failed: HTTP {r.status_code}")
    print(f"Upload done. batch_id={batch_id}")
    return batch_id


def _poll_batch(batch_id: str, timeout=600, interval=5) -> dict:
    """Poll batch until done. Returns result data."""
    start = time.time()
    while time.time() - start < timeout:
        resp = requests.get(f"{BASE}/extract-results/batch/{batch_id}", headers=HEADERS)
        data = resp.json()["data"]
        results = data.get("extract_result", [])
        state = results[0]["state"] if results else "pending"
        elapsed = int(time.time() - start)

        if state == "done":
            print(f"[{elapsed}s] Extraction done.")
            return data
        if state == "failed":
            err = results[0].get("err_msg", "") if results else ""
            raise RuntimeError(f"[{elapsed}s] Extraction failed: {err}")
        print(f"[{elapsed}s] {state} ...")
        time.sleep(interval)
    raise TimeoutError(f"Timed out after {timeout}s")


def _download_zip(result_data: dict) -> bytes:
    """Extract the zip URL from result and download it."""
    # batch result
    results = result_data.get("extract_result", [])
    if results:
        url = results[0].get("full_zip_url")
        if url:
            print(f"Downloading result zip ...")
            return requests.get(url).content
    # single task result
    url = result_data.get("full_zip_url")
    if url:
        print(f"Downloading result zip ...")
        return requests.get(url).content
    raise RuntimeError(f"No zip URL in result: {result_data}")


# ---------------------------------------------------------------------------
# High-level: mimic `mineru -p <pdf> -o <output_dir>`
# ---------------------------------------------------------------------------

def mineru_parse(pdf_path: str, output_dir: str, **kwargs):
    """Parse a PDF via MinerU API and save results like the local CLI.

    Creates: <output_dir>/<pdf_stem>/auto/  with .md, images/, etc.
    """
    pdf_path = pathlib.Path(pdf_path).resolve()
    output_dir = pathlib.Path(output_dir)
    pdf_stem = pdf_path.stem

    # Target: <output_dir>/<pdf_stem>/auto/
    auto_dir = output_dir / pdf_stem / "auto"
    auto_dir.mkdir(parents=True, exist_ok=True)

    # 1. Upload & submit
    batch_id = _upload_and_submit(pdf_path, **kwargs)

    # 2. Poll
    result = _poll_batch(batch_id)

    # 3. Download zip
    zip_bytes = _download_zip(result)

    # 4. Extract zip into auto_dir
    with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
        zf.extractall(auto_dir)
        names = zf.namelist()

    # 5. Rename the main markdown to <pdf_stem>.md if needed
    md_files = [n for n in names if n.endswith(".md")]
    if md_files:
        src = auto_dir / md_files[0]
        dst = auto_dir / f"{pdf_stem}.md"
        if src != dst and src.exists():
            shutil.move(str(src), str(dst))

    print(f"Done! {len(names)} files extracted to {auto_dir}/")
    print(f"Markdown: {auto_dir / pdf_stem}.md")
    return str(auto_dir)


# ---------------------------------------------------------------------------
# CLI: python tools/mineru_api.py -p <pdf> -o <output_dir>
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="MinerU API — drop-in replacement for `mineru` CLI")
    parser.add_argument("-p", required=True, help="Input PDF path")
    parser.add_argument("-o", required=True, help="Output directory")
    parser.add_argument("--model", default=None,
                        choices=["pipeline", "vlm"],
                        help="Model version (default: server auto)")
    parser.add_argument("--ocr", action="store_true", help="Enable OCR")
    parser.add_argument("--lang", default="en", help="Language (default: en)")
    parser.add_argument("--pages", default=None,
                        help="Page ranges, e.g. '1-10' or '2,4-6'")
    args = parser.parse_args()

    kwargs = {"language": args.lang, "is_ocr": args.ocr}
    if args.model:
        kwargs["model_version"] = args.model
    if args.pages:
        kwargs["page_ranges"] = args.pages

    mineru_parse(args.p, args.o, **kwargs)


if __name__ == "__main__":
    main()
