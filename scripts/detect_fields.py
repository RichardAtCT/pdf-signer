#!/usr/bin/env python3
"""Signature field detection with a 3-stage priority chain.

1. PyHanko AcroForm field detection
2. Text placeholder scan (pdfminer.six)
3. Vision model detection (Anthropic Claude)
"""

import re
import sys
from pathlib import Path

# Text placeholder patterns (case-insensitive)
PLACEHOLDER_PATTERNS = [
    r"/s/",
    r"\[SIGNATURE\]",
    r"\[SIGN\s+HERE\]",
    r"\{\{signature\}\}",
    r"\{signature\}",
    r"_{5,}",  # 5+ underscores
    r"Signature:\s*$",
]


def detect_pyhanko_fields(pdf_path):
    """Stage 1: Check for existing AcroForm signature fields using PyHanko.

    Returns dict with field info or None.
    """
    try:
        from pyhanko.pdf_utils.reader import PdfFileReader
    except ImportError:
        print("Warning: pyhanko not available for field detection.", file=sys.stderr)
        return None

    try:
        with open(pdf_path, "rb") as f:
            reader = PdfFileReader(f)
            fields = reader.embedded_signatures

            # Check for unsigned signature form fields
            root = reader.root
            acroform = root.get("/AcroForm")
            if acroform is None:
                return None

            acroform = acroform.get_object()
            form_fields = acroform.get("/Fields")
            if form_fields is None:
                return None

            for field_ref in form_fields:
                field = field_ref.get_object()
                ft = field.get("/FT")
                if ft is not None and str(ft) == "/Sig":
                    # Check if already signed
                    if field.get("/V") is not None:
                        continue
                    # Found unsigned signature field
                    field_name = str(field.get("/T", "Signature"))
                    # Try to get the widget annotation for position
                    rect = field.get("/Rect")
                    page_num = None

                    if rect:
                        rect_vals = [float(v) for v in rect]
                        x = rect_vals[0]
                        y = rect_vals[1]
                        width = rect_vals[2] - rect_vals[0]
                        height = rect_vals[3] - rect_vals[1]
                    else:
                        x, y, width, height = 400, 100, 200, 50

                    return {
                        "method": "pyhanko_field",
                        "field_name": field_name,
                        "page": page_num or 1,
                        "x": x,
                        "y": y,
                        "width": width,
                        "height": height,
                    }
    except Exception as e:
        print(f"Warning: PyHanko field detection failed: {e}", file=sys.stderr)

    return None


def detect_text_placeholders(pdf_path):
    """Stage 2: Scan text layer for signature placeholder patterns.

    Returns dict with location info or None.
    """
    try:
        from pdfminer.high_level import extract_pages
        from pdfminer.layout import LTTextBox, LTTextLine, LTChar, LAParams
    except ImportError:
        print("Warning: pdfminer.six not available for text detection.", file=sys.stderr)
        return None

    compiled_patterns = [re.compile(p, re.IGNORECASE) for p in PLACEHOLDER_PATTERNS]

    try:
        for page_num, page_layout in enumerate(extract_pages(str(pdf_path), laparams=LAParams()), 1):
            page_width = page_layout.width
            page_height = page_layout.height

            for element in page_layout:
                if isinstance(element, (LTTextBox, LTTextLine)):
                    text = element.get_text().strip()
                    for pattern in compiled_patterns:
                        if pattern.search(text):
                            bbox = element.bbox  # (x0, y0, x1, y1) bottom-left origin
                            return {
                                "method": "text_placeholder",
                                "pattern_matched": pattern.pattern,
                                "text": text[:100],
                                "page": page_num,
                                "x": bbox[0],
                                "y": bbox[1],
                                "width": min(200, bbox[2] - bbox[0]),
                                "height": max(50, bbox[3] - bbox[1]),
                                "page_width": page_width,
                                "page_height": page_height,
                            }
    except Exception as e:
        print(f"Warning: Text placeholder detection failed: {e}", file=sys.stderr)

    return None


def detect_vision(pdf_path):
    """Stage 3: Use vision model to find signature location.

    Returns dict with location info or None.
    """
    try:
        from scripts.vision_detect import detect_signature_vision, vision_coords_to_pdf
    except ImportError:
        # Try relative import for direct script execution
        try:
            from vision_detect import detect_signature_vision, vision_coords_to_pdf
        except ImportError:
            print("Warning: vision_detect module not available.", file=sys.stderr)
            return None

    result = detect_signature_vision(pdf_path)
    if result and result.get("found"):
        # We need page dimensions to convert percentages to points
        try:
            from pyhanko.pdf_utils.reader import PdfFileReader
            with open(pdf_path, "rb") as f:
                reader = PdfFileReader(f)
                page = reader.root["/Pages"]["/Kids"][result["page"] - 1].get_object()
                media_box = page["/MediaBox"]
                page_width = float(media_box[2])
                page_height = float(media_box[3])
        except Exception:
            # Default to US Letter
            page_width, page_height = 612, 792

        x, y = vision_coords_to_pdf(
            result["x_pct"], result["y_pct"], page_width, page_height
        )

        return {
            "method": "vision",
            "page": result["page"],
            "x": x,
            "y": y - 25,  # Offset up slightly so signature sits on the line
            "width": 200,
            "height": 50,
            "description": result.get("description", ""),
        }

    return None


def detect_signature_location(pdf_path):
    """Run the full detection chain. Returns detection result dict or None."""
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    # Stage 1: PyHanko field detection
    result = detect_pyhanko_fields(pdf_path)
    if result:
        return result

    # Stage 2: Text placeholder scan
    result = detect_text_placeholders(pdf_path)
    if result:
        return result

    # Stage 3: Vision model detection
    result = detect_vision(pdf_path)
    if result:
        return result

    # No detection succeeded
    return None


if __name__ == "__main__":
    import json

    if len(sys.argv) < 2:
        print("Usage: detect_fields.py <input.pdf>", file=sys.stderr)
        sys.exit(1)

    result = detect_signature_location(sys.argv[1])
    if result:
        print(json.dumps(result, indent=2))
    else:
        print("No signature location detected.", file=sys.stderr)
        sys.exit(1)
