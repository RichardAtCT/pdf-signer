#!/usr/bin/env python3
"""Main PDF signing script — entry point for the pdf-signer skill."""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure parent dir is on path for imports
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parent))
sys.path.insert(0, str(SCRIPT_DIR))


def get_page_count(pdf_path):
    """Get total number of pages."""
    from pyhanko.pdf_utils.reader import PdfFileReader
    with open(pdf_path, "rb") as f:
        reader = PdfFileReader(f)
        return int(reader.root["/Pages"]["/Count"])


def get_page_dimensions(pdf_path, page_num=1):
    """Get width and height of a PDF page in points."""
    from pyhanko.pdf_utils.reader import PdfFileReader
    with open(pdf_path, "rb") as f:
        reader = PdfFileReader(f)
        pages = reader.root["/Pages"]["/Kids"]
        page = pages[page_num - 1].get_object()
        media_box = page.get("/MediaBox") or page.get("/CropBox")
        if media_box:
            return float(media_box[2]), float(media_box[3])
    return 612, 792


def resolve_named_position(pdf_path, position_name):
    """Convert a named position to page + coordinates."""
    page_count = get_page_count(pdf_path)
    page_width, _ = get_page_dimensions(pdf_path, page_count)

    positions = {
        "last-page-bottom-right": {
            "page": page_count, "x": page_width - 220, "y": 60,
            "width": 200, "height": 50,
        },
        "last-page-bottom-left": {
            "page": page_count, "x": 20, "y": 60,
            "width": 200, "height": 50,
        },
    }
    return positions.get(position_name)


def load_signer(cert_path, passphrase):
    """Load a SimpleSigner from the PKCS#12 certificate."""
    from pyhanko.sign import signers
    return signers.SimpleSigner.load_pkcs12(
        pfx_file=str(cert_path),
        passphrase=passphrase.encode(),
    )


def build_stamp_style():
    """Build the visible signature stamp style."""
    from pyhanko.stamp import TextStampStyle

    sig_img = Path.home() / ".openclaw" / "workspace" / ".certs" / "signature.png"
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%-d %B %Y")

    if sig_img.exists():
        return TextStampStyle(
            stamp_text="Digitally signed\n%(ts)s",
            background=str(sig_img),
            background_opacity=1.0,
        )
    return TextStampStyle(
        stamp_text=f"PDF Signer\n{date_str}\nDigitally signed",
    )


def sign_pdf(input_path, output_path, page=None, x=None, y=None,
             width=200, height=50, invisible=False, position=None):
    """Sign a PDF document. Returns a result dict."""
    from gen_cert import ensure_cert
    from pyhanko.sign import signers, fields as sig_fields
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign.signers.pdf_signer import PdfSigner

    input_path = Path(input_path).resolve()
    output_path = Path(output_path).resolve()

    if not input_path.exists():
        return {"success": False, "error": f"Input file not found: {input_path}", "detection_method": None}

    cert_path, passphrase = ensure_cert()
    signer = load_signer(cert_path, passphrase)
    detection_method = None
    field_name = None

    # Auto-detection chain
    if page is None and x is None and y is None and position is None and not invisible:
        from detect_fields import detect_signature_location
        detection = detect_signature_location(input_path)

        if detection is None:
            return {
                "success": False,
                "error": (
                    "No signature location detected. Re-run with explicit placement:\n"
                    f"  sign.py {input_path} {output_path} --page 1 --x 400 --y 100\n"
                    f"  sign.py {input_path} {output_path} --position last-page-bottom-right"
                ),
                "detection_method": None,
            }

        detection_method = detection["method"]
        page = detection.get("page", 1)
        x = detection.get("x", 400)
        y = detection.get("y", 100)
        width = detection.get("width", 200)
        height = detection.get("height", 50)
        field_name = detection.get("field_name")

    # Resolve named position
    if position:
        pos = resolve_named_position(str(input_path), position)
        if pos is None:
            return {
                "success": False,
                "error": f"Unknown position: {position}",
                "detection_method": None,
            }
        page, x, y = pos["page"], pos["x"], pos["y"]
        width, height = pos["width"], pos["height"]
        detection_method = "manual"

    if invisible:
        detection_method = "manual"

    # Defaults
    if page is None:
        page = 1
    if x is None:
        x = 400
    if y is None:
        y = 100

    try:
        with open(input_path, "rb") as inf:
            writer = IncrementalPdfFileWriter(inf)
            sig_field_name = field_name or "Signature"

            if invisible:
                sig_fields.append_signature_field(
                    writer, sig_fields.SigFieldSpec(sig_field_name=sig_field_name)
                )
                meta = signers.PdfSignatureMetadata(field_name=sig_field_name)
                pdf_signer = PdfSigner(meta, signer)
            else:
                page_idx = page - 1
                sig_fields.append_signature_field(
                    writer,
                    sig_fields.SigFieldSpec(
                        sig_field_name=sig_field_name,
                        on_page=page_idx,
                        box=(x, y, x + width, y + height),
                    ),
                )
                meta = signers.PdfSignatureMetadata(field_name=sig_field_name)
                stamp_style = build_stamp_style()
                pdf_signer = PdfSigner(meta, signer, stamp_style=stamp_style)

            with open(output_path, "wb") as outf:
                pdf_signer.sign_pdf(writer, output=outf)

    except Exception as e:
        return {"success": False, "error": str(e), "detection_method": detection_method}

    return {
        "success": True,
        "output": str(output_path),
        "detection_method": detection_method or "manual",
        "signature_page": page,
        "signature_location": {"x": round(x, 1), "y": round(y, 1)},
    }


def main():
    parser = argparse.ArgumentParser(description="Sign a PDF document")
    parser.add_argument("input", help="Input PDF file path")
    parser.add_argument("output", help="Output signed PDF file path")
    parser.add_argument("--page", type=int, help="Page number (1-based)")
    parser.add_argument("--x", type=float, help="X coordinate (PDF points, bottom-left origin)")
    parser.add_argument("--y", type=float, help="Y coordinate (PDF points, bottom-left origin)")
    parser.add_argument("--width", type=float, default=200, help="Signature width (default: 200)")
    parser.add_argument("--height", type=float, default=50, help="Signature height (default: 50)")
    parser.add_argument("--position", choices=["last-page-bottom-right", "last-page-bottom-left"],
                        help="Named position shortcut")
    parser.add_argument("--invisible", action="store_true", help="Invisible signature (cryptographic only)")

    args = parser.parse_args()

    result = sign_pdf(
        input_path=args.input,
        output_path=args.output,
        page=args.page,
        x=args.x,
        y=args.y,
        width=args.width,
        height=args.height,
        invisible=args.invisible,
        position=args.position,
    )

    print(json.dumps(result, indent=2))
    if not result["success"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
