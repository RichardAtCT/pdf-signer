#!/usr/bin/env python3
"""Main PDF signing script — entry point for the pdf-signer tool."""

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

ASSETS_DIR = SCRIPT_DIR.parent / "assets"


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


def get_signer_name(cert_path, passphrase, name_override=None):
    """Resolve the signer display name."""
    if name_override:
        return name_override
    env_name = os.environ.get("PDF_SIGNER_NAME")
    if env_name:
        return env_name
    # Read from cert CN
    from gen_cert import get_cert_cn
    cn = get_cert_cn(cert_path, passphrase)
    return cn or "Signer"


def get_initials_text(signer_name, initials_text_override=None):
    """Derive initials from signer name or overrides."""
    if initials_text_override:
        return initials_text_override
    env_initials = os.environ.get("PDF_SIGNER_INITIALS")
    if env_initials:
        return env_initials
    # Auto-derive: first letter of each word
    if signer_name:
        return "".join(word[0].upper() for word in signer_name.split() if word)
    return "X"


def _make_handwriting_text_box_style():
    """Create a TextBoxStyle using the bundled GreatVibes cursive font, or None."""
    font_path = ASSETS_DIR / "GreatVibes-Regular.ttf"
    if not font_path.exists():
        return None
    try:
        from pyhanko.pdf_utils.font.opentype import GlyphAccumulatorFactory
        from pyhanko.pdf_utils.text import TextBoxStyle

        font = GlyphAccumulatorFactory(font_file=str(font_path))
        return TextBoxStyle(font=font)
    except Exception as e:
        print(f"Warning: Could not load handwriting font: {e}", file=sys.stderr)
        return None


def build_stamp_style(signer_name, signature_image=None):
    """Build the visible signature stamp style."""
    from pyhanko.stamp import TextStampStyle

    sig_img = signature_image or os.environ.get("PDF_SIGNER_IMAGE")

    now = datetime.now(timezone.utc)
    date_str = now.strftime("%-d %B %Y")

    if sig_img and Path(sig_img).exists():
        return TextStampStyle(
            stamp_text=f"Digitally signed\n{date_str}",
            background=str(sig_img),
            background_opacity=1.0,
        )

    style_kwargs = {
        "stamp_text": f"{signer_name}\n{date_str}\nDigitally signed",
    }

    text_box_style = _make_handwriting_text_box_style()
    if text_box_style:
        style_kwargs["text_box_style"] = text_box_style

    return TextStampStyle(**style_kwargs)


def build_initials_stamp_style(initials_text, initials_image=None):
    """Build the visible initials stamp style — smaller, no date/label."""
    from pyhanko.stamp import TextStampStyle

    ini_img = initials_image or os.environ.get("PDF_SIGNER_INITIALS_IMAGE")

    if ini_img and Path(ini_img).exists():
        return TextStampStyle(
            stamp_text="",
            background=str(ini_img),
            background_opacity=1.0,
        )

    style_kwargs = {"stamp_text": initials_text}
    text_box_style = _make_handwriting_text_box_style()
    if text_box_style:
        style_kwargs["text_box_style"] = text_box_style

    return TextStampStyle(**style_kwargs)


def _find_initials_positions(pdf_path, total_pages):
    """Find clear whitespace positions for initials on each page using pdfminer.

    Preferred order: bottom-right → bottom-left → top-right → top-left.
    Falls back to bottom-left x=20, y=20 if scanning fails.
    """
    try:
        from pdfminer.high_level import extract_pages
        from pdfminer.layout import LTTextBox, LTTextLine, LTFigure, LTImage, LAParams
    except ImportError:
        return [{"page": p, "x": 20, "y": 20} for p in range(1, total_pages + 1)]

    ini_w, ini_h = 80, 30
    margin = 10  # padding from page edge
    results = []

    try:
        page_layouts = list(extract_pages(str(pdf_path), laparams=LAParams()))
    except Exception:
        return [{"page": p, "x": 20, "y": 20} for p in range(1, total_pages + 1)]

    for page_num in range(1, total_pages + 1):
        if page_num - 1 < len(page_layouts):
            page_layout = page_layouts[page_num - 1]
            pw, ph = page_layout.width, page_layout.height

            # Collect all content bounding boxes
            content_boxes = []
            for element in page_layout:
                if isinstance(element, (LTTextBox, LTTextLine, LTFigure, LTImage)):
                    content_boxes.append(element.bbox)  # (x0, y0, x1, y1)

            def _is_clear(cx, cy):
                """Check if a rectangle at (cx, cy) with size ini_w x ini_h is clear."""
                for bx0, by0, bx1, by1 in content_boxes:
                    # Check overlap
                    if cx < bx1 and cx + ini_w > bx0 and cy < by1 and cy + ini_h > by0:
                        return False
                return True

            # Candidate positions: bottom-right, bottom-left, top-right, top-left
            candidates = [
                (pw - ini_w - margin, margin),           # bottom-right
                (margin, margin),                         # bottom-left
                (pw - ini_w - margin, ph - ini_h - margin),  # top-right
                (margin, ph - ini_h - margin),            # top-left
            ]

            placed = False
            for cx, cy in candidates:
                if _is_clear(cx, cy):
                    results.append({"page": page_num, "x": round(cx, 1), "y": round(cy, 1)})
                    placed = True
                    break

            if not placed:
                # Fallback: bottom-left
                results.append({"page": page_num, "x": 20, "y": 20})
        else:
            results.append({"page": page_num, "x": 20, "y": 20})

    return results


def place_initials_stamps(writer, initials_locations, initials_style):
    """Place initials annotation stamps on the PDF (non-signing visual stamps).

    Uses pyhanko's TextStamp to add visual-only stamps for initials.
    """
    from pyhanko.stamp import TextStamp
    from pyhanko.pdf_utils.layout import BoxConstraints

    for loc in initials_locations:
        page_idx = loc["page"] - 1
        w = loc.get("width", 80)
        h = loc.get("height", 30)
        stamp = TextStamp(
            writer=writer,
            style=initials_style,
            box=BoxConstraints(width=w, height=h),
        )
        stamp.apply(dest_page=page_idx, x=loc["x"], y=loc["y"])


def _detect_signature_for_page(pdf_path, page_num):
    """Detect signature location on a specific page, or return a default."""
    from detect_fields import detect_signature_on_page
    detection = detect_signature_on_page(pdf_path, page_num)
    if detection:
        return {
            "page": page_num,
            "x": detection.get("x", 400),
            "y": detection.get("y", 100),
            "width": detection.get("width", 200),
            "height": detection.get("height", 50),
            "detection_method": detection["method"],
            "field_name": detection.get("field_name"),
        }
    # Default: bottom-right area
    return {
        "page": page_num,
        "x": 400,
        "y": 50,
        "width": 200,
        "height": 50,
        "detection_method": "default",
        "field_name": None,
    }


def _apply_signer_suffix(field_name, signer_index):
    """Append _s{N} suffix to a field name when signer_index > 1."""
    if signer_index and signer_index > 1:
        return f"{field_name}_s{signer_index}"
    return field_name


def sign_pdf(input_path, output_path, page=None, x=None, y=None,
             width=200, height=50, invisible=False, position=None,
             name=None, email=None, cert=None, signature_image=None,
             initials=False, initials_all_pages=False,
             initials_text=None, initials_image=None,
             sign_pages=None, signer_index=1):
    """Sign a PDF document. Returns a result dict."""
    from gen_cert import ensure_cert
    from pyhanko.sign import signers, fields as sig_fields
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign.signers.pdf_signer import PdfSigner

    input_path = Path(input_path).resolve()
    output_path = Path(output_path).resolve()

    if not input_path.exists():
        return {"success": False, "error": f"Input file not found: {input_path}", "detection_method": None}

    cert_path, passphrase = ensure_cert(cert_path=cert, name=name, email=email)
    signer = load_signer(cert_path, passphrase)
    signer_name = get_signer_name(cert_path, passphrase, name_override=name)
    detection_method = None
    field_name = None
    initials_placed = []

    # Determine initials locations
    if initials_all_pages:
        total_pages = get_page_count(str(input_path))
        initials_placed = _find_initials_positions(str(input_path), total_pages)
    elif initials:
        # Detect initials locations or use signature detection location with initials size
        from detect_fields import detect_initials_locations
        detected = detect_initials_locations(input_path)
        if detected:
            initials_placed = detected

    # Use initials mode: place initials at detected/specified location instead of full signature
    use_initials_as_signature = initials and not initials_all_pages

    # --- Multi-page signing via --sign-pages ---
    if sign_pages:
        # Resolve signature placements for each requested page
        sig_placements = []
        for pg in sign_pages:
            info = _detect_signature_for_page(str(input_path), pg)
            sig_placements.append(info)

        # Use tempfiles for incremental signing passes
        import shutil
        import tempfile

        stamp_style = build_stamp_style(signer_name, signature_image)

        # First pass: place initials + first signature
        first = sig_placements[0]
        try:
            with open(input_path, "rb") as inf:
                writer = IncrementalPdfFileWriter(inf)

                # Place initials stamps before signing
                if initials_placed:
                    ini_text = get_initials_text(signer_name, initials_text)
                    ini_style = build_initials_stamp_style(ini_text, initials_image)
                    place_initials_stamps(writer, initials_placed, ini_style)

                sig_field_name = first["field_name"] or "Signature_p%d" % first["page"]
                sig_field_name = _apply_signer_suffix(sig_field_name, signer_index)
                page_idx = first["page"] - 1
                sig_fields.append_signature_field(
                    writer,
                    sig_fields.SigFieldSpec(
                        sig_field_name=sig_field_name,
                        on_page=page_idx,
                        box=(first["x"], first["y"],
                             first["x"] + first["width"], first["y"] + first["height"]),
                    ),
                )
                meta = signers.PdfSignatureMetadata(field_name=sig_field_name)
                pdf_signer = PdfSigner(meta, signer, stamp_style=stamp_style)

                if len(sig_placements) == 1:
                    # Only one signature — write directly to output
                    with open(output_path, "wb") as outf:
                        pdf_signer.sign_pdf(writer, output=outf)
                else:
                    # Write to temp file for next pass
                    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
                    tmp_path = tmp.name
                    pdf_signer.sign_pdf(writer, output=tmp)
                    tmp.close()

        except Exception as e:
            return {"success": False, "error": str(e), "detection_method": None}

        # Subsequent passes for remaining signatures
        if len(sig_placements) > 1:
            try:
                for i, placement in enumerate(sig_placements[1:], 2):
                    with open(tmp_path, "rb") as inf:
                        writer = IncrementalPdfFileWriter(inf)
                        sig_field_name = placement["field_name"] or "Signature_p%d" % placement["page"]
                        sig_field_name = _apply_signer_suffix(sig_field_name, signer_index)
                        page_idx = placement["page"] - 1
                        sig_fields.append_signature_field(
                            writer,
                            sig_fields.SigFieldSpec(
                                sig_field_name=sig_field_name,
                                on_page=page_idx,
                                box=(placement["x"], placement["y"],
                                     placement["x"] + placement["width"],
                                     placement["y"] + placement["height"]),
                            ),
                        )
                        meta = signers.PdfSignatureMetadata(field_name=sig_field_name)
                        pdf_signer = PdfSigner(meta, signer, stamp_style=stamp_style)

                        is_last = (i == len(sig_placements))
                        if is_last:
                            with open(output_path, "wb") as outf:
                                pdf_signer.sign_pdf(writer, output=outf)
                        else:
                            new_tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
                            new_tmp_path = new_tmp.name
                            pdf_signer.sign_pdf(writer, output=new_tmp)
                            new_tmp.close()
                            os.unlink(tmp_path)
                            tmp_path = new_tmp_path

                # Clean up last temp
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)

            except Exception as e:
                # Clean up temp files
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                return {"success": False, "error": str(e), "detection_method": None}

        result = {
            "success": True,
            "output": str(output_path),
            "signatures_placed": [
                {
                    "page": p["page"],
                    "x": round(p["x"], 1),
                    "y": round(p["y"], 1),
                    "detection_method": p["detection_method"],
                }
                for p in sig_placements
            ],
        }
        if initials_placed:
            result["initials_placed"] = [
                {"page": loc["page"], "x": round(loc["x"], 1), "y": round(loc["y"], 1)}
                for loc in initials_placed
            ]
        return result

    # --- Standard single-signature path (unchanged) ---

    # Auto-detection chain for signature
    if page is None and x is None and y is None and position is None and not invisible:
        if use_initials_as_signature and initials_placed:
            # Use first initials location as the stamp location
            det = initials_placed[0]
            page = det["page"]
            x = det["x"]
            y = det["y"]
            width = det.get("width", 80)
            height = det.get("height", 30)
            detection_method = "text_placeholder"
        else:
            from detect_fields import detect_signature_location
            detection = detect_signature_location(input_path)

            if detection is None and not (initials_all_pages or invisible):
                return {
                    "success": False,
                    "error": (
                        "No signature location detected. Re-run with explicit placement:\n"
                        f"  sign.py {input_path} {output_path} --page 1 --x 400 --y 100\n"
                        f"  sign.py {input_path} {output_path} --position last-page-bottom-right"
                    ),
                    "detection_method": None,
                }

            if detection:
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

    # If --initials flag with no detected locations, use signature location with initials stamp
    if use_initials_as_signature and not initials_placed:
        initials_placed = [{"page": page, "x": x, "y": y}]
        width = 80
        height = 30

    try:
        with open(input_path, "rb") as inf:
            writer = IncrementalPdfFileWriter(inf)
            sig_field_name = field_name or "Signature"
            sig_field_name = _apply_signer_suffix(sig_field_name, signer_index)

            # Place initials stamps before signing (visual-only annotations)
            if initials_placed:
                ini_text = get_initials_text(signer_name, initials_text)
                ini_style = build_initials_stamp_style(ini_text, initials_image)
                place_initials_stamps(writer, initials_placed, ini_style)

            if invisible:
                sig_fields.append_signature_field(
                    writer, sig_fields.SigFieldSpec(sig_field_name=sig_field_name)
                )
                meta = signers.PdfSignatureMetadata(field_name=sig_field_name)
                pdf_signer = PdfSigner(meta, signer)
            elif use_initials_as_signature:
                # For --initials mode, the signature field uses initials appearance
                page_idx = page - 1
                ini_text = get_initials_text(signer_name, initials_text)
                ini_style = build_initials_stamp_style(ini_text, initials_image)
                sig_fields.append_signature_field(
                    writer,
                    sig_fields.SigFieldSpec(
                        sig_field_name=sig_field_name,
                        on_page=page_idx,
                        box=(x, y, x + width, y + height),
                    ),
                )
                meta = signers.PdfSignatureMetadata(field_name=sig_field_name)
                pdf_signer = PdfSigner(meta, signer, stamp_style=ini_style)
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
                stamp_style = build_stamp_style(signer_name, signature_image)
                pdf_signer = PdfSigner(meta, signer, stamp_style=stamp_style)

            with open(output_path, "wb") as outf:
                pdf_signer.sign_pdf(writer, output=outf)

    except Exception as e:
        return {"success": False, "error": str(e), "detection_method": detection_method}

    result = {
        "success": True,
        "output": str(output_path),
        "detection_method": detection_method or "manual",
        "signature_page": page,
        "signature_location": {"x": round(x, 1), "y": round(y, 1)},
    }

    if initials_placed:
        result["initials_placed"] = [
            {"page": loc["page"], "x": round(loc["x"], 1), "y": round(loc["y"], 1)}
            for loc in initials_placed
        ]

    return result


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
    parser.add_argument("--name", help="Signer display name (overrides PDF_SIGNER_NAME / cert CN)")
    parser.add_argument("--email", help="Signer email (used in cert generation)")
    parser.add_argument("--cert", help="Path to PKCS#12 certificate file")
    parser.add_argument("--signature-image", help="Path to signature PNG image")
    parser.add_argument("--initials", action="store_true",
                        help="Place initials stamp instead of full signature")
    parser.add_argument("--initials-all-pages", action="store_true",
                        help="Place initials on every page at bottom-left, then sign")
    parser.add_argument("--initials-text", help="Custom initials text (e.g. 'RA')")
    parser.add_argument("--initials-image", help="Path to initials PNG image")
    parser.add_argument("--sign-pages", type=str, default=None,
                        help="Comma-separated page numbers for full signature placement (1-based)")
    parser.add_argument("--signer-index", type=int, default=1,
                        help="Signer index (default: 1). Use 2+ for chained multi-signer signing to avoid field name collisions")

    args = parser.parse_args()

    # Parse --sign-pages into a list of ints
    sign_pages = None
    if args.sign_pages:
        try:
            sign_pages = [int(p.strip()) for p in args.sign_pages.split(",")]
        except ValueError:
            print(json.dumps({"success": False, "error": "--sign-pages must be comma-separated integers"}))
            sys.exit(1)

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
        name=args.name,
        email=args.email,
        cert=args.cert,
        signature_image=args.signature_image,
        initials=args.initials,
        initials_all_pages=args.initials_all_pages,
        initials_text=args.initials_text,
        initials_image=args.initials_image,
        sign_pages=sign_pages,
        signer_index=args.signer_index,
    )

    print(json.dumps(result, indent=2))
    if not result["success"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
