#!/usr/bin/env python3
"""Process PDFs via Mathpix API — upload, poll status, download markdown.

Usage:
    # Process a single PDF
    python tools/mathpix_api.py papers/agentflow/2510.05592.pdf

    # Process a PDF and save to specific output path
    python tools/mathpix_api.py papers/agentflow/2510.05592.pdf -o papers/agentflow/metadata/mathpix.md

    # Check status of a previous job
    python tools/mathpix_api.py --status 7f0d8e2a-38eb-4775-ac45-05a61bd6b10b

    # Process all PDFs in a paper directory
    python tools/mathpix_api.py papers/agentflow/

Environment variables (or pass via --app-id / --app-key):
    MATHPIX_APP_ID
    MATHPIX_APP_KEY
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    print("Error: 'requests' package required. Install with: pip install requests", file=sys.stderr)
    sys.exit(1)

API_BASE = "https://api.mathpix.com/v3/pdf"


def get_credentials(args):
    app_id = args.app_id or os.environ.get("MATHPIX_APP_ID", "lupantech_gmail_com_e2a89b_110220")
    app_key = args.app_key or os.environ.get("MATHPIX_APP_KEY", "8f72f22600d27a18937d67a9c42a057a68a462eeaddfcca06e9bbd23a72e1e05")
    if not app_id or not app_key:
        print("Error: MATHPIX_APP_ID and MATHPIX_APP_KEY required.", file=sys.stderr)
        print("Set via environment variables or --app-id / --app-key flags.", file=sys.stderr)
        sys.exit(1)
    return app_id, app_key


def headers(app_id, app_key):
    return {"app_id": app_id, "app_key": app_key}


def upload_pdf(pdf_path, app_id, app_key):
    """Upload a PDF file and return the pdf_id."""
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        print(f"Error: {pdf_path} not found", file=sys.stderr)
        return None

    with open(pdf_path, "rb") as f:
        resp = requests.post(
            API_BASE,
            headers=headers(app_id, app_key),
            files={"file": (pdf_path.name, f, "application/pdf")},
            data={"options_json": json.dumps({"conversion_formats": {"md": True}})},
        )

    if resp.status_code != 200:
        print(f"Error uploading: {resp.status_code} {resp.text}", file=sys.stderr)
        return None

    data = resp.json()
    if "error" in data:
        print(f"API error: {data['error']}", file=sys.stderr)
        return None

    pdf_id = data.get("pdf_id", "")
    print(f"Uploaded {pdf_path.name} -> pdf_id: {pdf_id}")
    return pdf_id


def check_status(pdf_id, app_id, app_key):
    """Check processing status. Returns status dict."""
    resp = requests.get(f"{API_BASE}/{pdf_id}", headers=headers(app_id, app_key))
    if resp.status_code != 200:
        print(f"Error checking status: {resp.status_code} {resp.text}", file=sys.stderr)
        return None
    return resp.json()


def wait_for_completion(pdf_id, app_id, app_key, poll_interval=5, timeout=600):
    """Poll until processing is complete. Returns final status dict."""
    start = time.time()
    while time.time() - start < timeout:
        status = check_status(pdf_id, app_id, app_key)
        if status is None:
            return None
        if "error" in status:
            print(f"API error: {status['error']}", file=sys.stderr)
            return None

        state = status.get("status", "")
        pct = status.get("percent_done", 0)
        pages = status.get("num_pages", "?")
        done = status.get("num_pages_completed", 0)

        if state == "completed":
            print(f"Completed: {pages} pages")
            return status

        print(f"  Processing: {done}/{pages} pages ({pct:.0f}%)", end="\r")
        time.sleep(poll_interval)

    print(f"\nTimeout after {timeout}s", file=sys.stderr)
    return None


def download_images(md_text, output_dir):
    """Download all Mathpix CDN images referenced in markdown, return updated text."""
    import re
    img_dir = Path(output_dir) / "images"
    img_dir.mkdir(parents=True, exist_ok=True)

    pattern = r'!\[([^\]]*)\]\((https://cdn\.mathpix\.com/cropped/[^)]+)\)'
    matches = list(re.finditer(pattern, md_text))
    if not matches:
        return md_text

    print(f"Downloading {len(matches)} images...")
    for i, m in enumerate(matches):
        url = m.group(2)
        # Generate filename from url hash
        ext = "jpg"
        fname = f"img_{i+1:03d}.{ext}"
        local_path = img_dir / fname

        try:
            resp = requests.get(url, timeout=30)
            if resp.status_code == 200:
                local_path.write_bytes(resp.content)
            else:
                print(f"  Warning: failed to download {fname}: {resp.status_code}", file=sys.stderr)
                continue
        except Exception as e:
            print(f"  Warning: failed to download {fname}: {e}", file=sys.stderr)
            continue

        # Replace CDN URL with local path
        md_text = md_text.replace(url, f"images/{fname}")

    print(f"  Saved {len(matches)} images to {img_dir}")
    return md_text


def download_md(pdf_id, output_path, app_id, app_key):
    """Download the markdown result and its images."""
    resp = requests.get(f"{API_BASE}/{pdf_id}.md", headers=headers(app_id, app_key))
    if resp.status_code != 200:
        print(f"Error downloading: {resp.status_code} {resp.text}", file=sys.stderr)
        return False

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Download images and rewrite paths
    md_text = download_images(resp.text, output_path.parent)

    output_path.write_text(md_text, encoding="utf-8")
    lines = md_text.count("\n") + 1
    print(f"Saved {output_path} ({lines} lines, {len(md_text):,} bytes)")
    return True


def process_pdf(pdf_path, output_path, app_id, app_key):
    """Full pipeline: upload -> wait -> download."""
    pdf_id = upload_pdf(pdf_path, app_id, app_key)
    if not pdf_id:
        return False

    status = wait_for_completion(pdf_id, app_id, app_key)
    if not status:
        return False

    return download_md(pdf_id, output_path, app_id, app_key)


def process_paper_dir(paper_dir, app_id, app_key):
    """Process all PDFs in a paper directory."""
    paper_dir = Path(paper_dir)
    pdfs = sorted(paper_dir.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs found in {paper_dir}", file=sys.stderr)
        return False

    for pdf in pdfs:
        arxiv_id = pdf.stem
        output = paper_dir / "metadata" / arxiv_id / "mathpix" / f"{arxiv_id}.md"
        print(f"\n{'='*60}")
        print(f"Processing: {pdf.name}")
        print(f"Output: {output}")
        print(f"{'='*60}")
        process_pdf(pdf, output, app_id, app_key)

    return True


def main():
    parser = argparse.ArgumentParser(description="Process PDFs via Mathpix API")
    parser.add_argument("input", nargs="?", help="PDF file or paper directory")
    parser.add_argument("-o", "--output", help="Output markdown path (default: auto)")
    parser.add_argument("--status", help="Check status of a pdf_id")
    parser.add_argument("--download", help="Download result for a pdf_id (use with -o)")
    parser.add_argument("--app-id", default="", help="Mathpix app_id")
    parser.add_argument("--app-key", default="", help="Mathpix app_key")
    args = parser.parse_args()

    app_id, app_key = get_credentials(args)

    # Check status mode
    if args.status:
        status = check_status(args.status, app_id, app_key)
        if status:
            print(json.dumps(status, indent=2))
        return

    # Download mode
    if args.download:
        output = args.output or f"{args.download}.md"
        download_md(args.download, output, app_id, app_key)
        return

    # Process mode
    if not args.input:
        parser.error("Provide a PDF file or paper directory")

    input_path = Path(args.input)

    if input_path.is_dir():
        process_paper_dir(input_path, app_id, app_key)
    elif input_path.is_file() and input_path.suffix == ".pdf":
        if args.output:
            output = args.output
        else:
            arxiv_id = input_path.stem
            output = input_path.parent / "metadata" / arxiv_id / "mathpix" / f"{arxiv_id}.md"
        process_pdf(input_path, output, app_id, app_key)
    else:
        parser.error(f"Not a PDF file or directory: {input_path}")


if __name__ == "__main__":
    main()
