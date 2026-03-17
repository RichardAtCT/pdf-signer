#!/usr/bin/env python3
"""Signature field detection with a 3-stage priority chain.

1. PyHanko AcroForm field detection
2. Text placeholder scan (pdfminer.six)
3. Vision model detection (Anthropic Claude)
"""

import re
import sys
from pathlib import Path

# High-priority signature placeholder patterns (case-insensitive)
SIGN_PATTERNS = [
    r"/s/",
    r"\[SIGNATURE\]",
    r"\[SIGN\s+HERE\]",
    r"\{\{signature\}\}",
    r"\{signature\}",
    r"Signature:\s*$",
    r"Sign\s+here",
    r"SIGNATURE\s+PURCHASER",
    r"SIGNATURE\s+SELLER",
    r"SIGNATURE\s+OF\s+PURCHASER",
    r"SIGNATURE\s+OF\s+SELLER",
    r"SIGNED\s+BY",
    r"Signature\s+of",
    r"PURCHASER.{0,20}SIGNATURE",
    r"x\s*_{5,}",
]

# Lower-priority name/title field patterns — used as fallback
NAME_FIELD_PATTERNS = [
    r"Name:\s*$",
    r"Purchaser:\s*$",
    r"Seller:\s*$",
]

# Underscore lines (ambiguous — lower than explicit sign patterns)
UNDERSCORE_PATTERNS = [
    r"_{5,}",  # 5+ underscores
]

# Combined for backward compat — but detection now uses ranked search
PLACEHOLDER_PATTERNS = SIGN_PATTERNS + UNDERSCORE_PATTERNS + NAME_FIELD_PATTERNS

# Initials placeholder patterns (case-insensitive)
INITIALS_PATTERNS = [
    r"\[INITIALS\]",
    r"\[INIT\]",
    r"/i/",
    r"Initials:\s*$",
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


def detect_text_placeholders(pdf_path, target_page=None):
    """Stage 2: Scan text layer for signature placeholder patterns.

    Uses ranked detection: explicit sign patterns > underscores > name fields.
    If both sign and name fields found on the same page, prefers the sign field.
    If target_page is provided, only considers candidates on that page.
    Returns dict with location info or None.
    """
    try:
        from pdfminer.high_level import extract_pages
        from pdfminer.layout import LTTextBox, LTTextLine, LTChar, LAParams
    except ImportError:
        print("Warning: pdfminer.six not available for text detection.", file=sys.stderr)
        return None

    sign_compiled = [re.compile(p, re.IGNORECASE) for p in SIGN_PATTERNS]
    underscore_compiled = [re.compile(p, re.IGNORECASE) for p in UNDERSCORE_PATTERNS]
    name_compiled = [re.compile(p, re.IGNORECASE) for p in NAME_FIELD_PATTERNS]

    # Collect candidates across all pages with priority tiers
    # tier 0 = sign patterns (highest), tier 1 = underscores, tier 2 = name fields
    candidates = []

    def _make_result(element, page_num, page_layout, pattern, tier, method="text_placeholder"):
        bbox = element.bbox
        return {
            "method": method,
            "pattern_matched": pattern.pattern,
            "text": element.get_text().strip()[:100],
            "page": page_num,
            "x": bbox[0],
            "y": bbox[1],
            "width": min(200, bbox[2] - bbox[0]),
            "height": max(50, bbox[3] - bbox[1]),
            "page_width": page_layout.width,
            "page_height": page_layout.height,
            "_tier": tier,
        }

    try:
        for page_num, page_layout in enumerate(extract_pages(str(pdf_path), laparams=LAParams()), 1):
            for element in page_layout:
                if not isinstance(element, (LTTextBox, LTTextLine)):
                    continue
                text = element.get_text().strip()
                for pattern in sign_compiled:
                    if pattern.search(text):
                        candidates.append(_make_result(element, page_num, page_layout, pattern, 0))
                        break
                else:
                    for pattern in underscore_compiled:
                        if pattern.search(text):
                            candidates.append(_make_result(element, page_num, page_layout, pattern, 1))
                            break
                    else:
                        for pattern in name_compiled:
                            if pattern.search(text):
                                candidates.append(_make_result(
                                    element, page_num, page_layout, pattern, 2,
                                    method="name_field_fallback",
                                ))
                                break
    except Exception as e:
        print(f"Warning: Text placeholder detection failed: {e}", file=sys.stderr)
        return None

    if target_page is not None:
        candidates = [c for c in candidates if c["page"] == target_page]

    if not candidates:
        return None

    # Pick best candidate: lowest tier wins; within same tier, last page then lowest y
    candidates.sort(key=lambda c: (c["_tier"], -c["page"], c["y"]))
    best = candidates[0]
    best.pop("_tier", None)
    return best


def detect_vision(pdf_path, target_page=None):
    """Stage 3: Use vision model to find signature location.

    If target_page is provided, only renders/checks that specific page.
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

    result = detect_signature_vision(pdf_path, target_page=target_page)
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


def detect_initials_text_placeholders(pdf_path):
    """Scan text layer for initials placeholder patterns.

    Returns a list of all matching locations (not just the first).
    """
    try:
        from pdfminer.high_level import extract_pages
        from pdfminer.layout import LTTextBox, LTTextLine, LAParams
    except ImportError:
        print("Warning: pdfminer.six not available for text detection.", file=sys.stderr)
        return []

    compiled_patterns = [re.compile(p, re.IGNORECASE) for p in INITIALS_PATTERNS]
    results = []

    try:
        for page_num, page_layout in enumerate(extract_pages(str(pdf_path), laparams=LAParams()), 1):
            for element in page_layout:
                if isinstance(element, (LTTextBox, LTTextLine)):
                    text = element.get_text().strip()
                    for pattern in compiled_patterns:
                        if pattern.search(text):
                            bbox = element.bbox
                            results.append({
                                "page": page_num,
                                "x": bbox[0],
                                "y": bbox[1],
                                "width": min(80, bbox[2] - bbox[0]),
                                "height": max(30, bbox[3] - bbox[1]),
                            })
                            break  # One match per element is enough
    except Exception as e:
        print(f"Warning: Initials text detection failed: {e}", file=sys.stderr)

    return results


def detect_initials_vision(pdf_path):
    """Use vision model to find all initials locations on each page.

    Returns a list of locations.
    """
    try:
        from vision_detect import detect_signature_vision, vision_coords_to_pdf
    except ImportError:
        try:
            from scripts.vision_detect import detect_signature_vision, vision_coords_to_pdf
        except ImportError:
            print("Warning: vision_detect module not available.", file=sys.stderr)
            return []

    import os
    import json as _json
    import base64
    import io

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return []

    try:
        import anthropic
        from pdf2image import convert_from_path
    except ImportError:
        return []

    client = anthropic.Anthropic(api_key=api_key)
    results = []

    try:
        images = convert_from_path(str(pdf_path), dpi=150, fmt="png")
    except Exception:
        return []

    for page_num, img in enumerate(images, 1):
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        img_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        prompt = (
            f"This is page {page_num} of a PDF document. "
            "Identify ALL initials boxes or places where initials should go. "
            "Return a JSON array of objects: "
            '[{"found": true, "x_pct": <0-100>, "y_pct": <0-100>}, ...] '
            "where x_pct and y_pct are the percentage position from top-left. "
            'If no initials location found, return [{"found": false}].'
        )

        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=500,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img_b64}},
                        {"type": "text", "text": prompt},
                    ],
                }],
            )
        except Exception:
            continue

        response_text = response.content[0].text.strip()
        try:
            start = response_text.find("[")
            end = response_text.rfind("]") + 1
            if start >= 0 and end > start:
                items = _json.loads(response_text[start:end])
                for item in items:
                    if item.get("found"):
                        try:
                            from pyhanko.pdf_utils.reader import PdfFileReader
                            with open(pdf_path, "rb") as f:
                                reader = PdfFileReader(f)
                                page = reader.root["/Pages"]["/Kids"][page_num - 1].get_object()
                                media_box = page["/MediaBox"]
                                pw, ph = float(media_box[2]), float(media_box[3])
                        except Exception:
                            pw, ph = 612, 792

                        x, y = vision_coords_to_pdf(item["x_pct"], item["y_pct"], pw, ph)
                        results.append({"page": page_num, "x": x, "y": y - 15, "width": 80, "height": 30})
        except (_json.JSONDecodeError, ValueError):
            continue

    return results


def detect_initials_locations(pdf_path):
    """Detect all initials placement locations in a PDF.

    Uses text placeholder scan first, then vision model fallback.
    Returns a list of location dicts with page, x, y, width, height.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    # Text placeholder scan
    results = detect_initials_text_placeholders(pdf_path)
    if results:
        return results

    # Vision fallback
    results = detect_initials_vision(pdf_path)
    if results:
        return results

    return []


def detect_signature_on_page(pdf_path, target_page):
    """Detect a signature field on a specific page number (1-based).

    Checks AcroForm fields and text placeholders limited to the target page.
    Returns detection result dict or None.
    """
    pdf_path = Path(pdf_path)

    # Check AcroForm fields on this page
    result = detect_pyhanko_fields(pdf_path)
    if result and result.get("page") == target_page:
        return result

    # Check text placeholders on the specific page
    result = detect_text_placeholders(pdf_path, target_page=target_page)
    if result:
        return result

    # Vision fallback — only render the target page
    result = detect_vision(pdf_path, target_page=target_page)
    if result and result.get("page") == target_page:
        return result

    return None


def _get_page_dimensions(pdf_path, page_num):
    """Get width and height of a PDF page in points."""
    try:
        from pyhanko.pdf_utils.reader import PdfFileReader
        with open(pdf_path, "rb") as f:
            reader = PdfFileReader(f)
            page = reader.root["/Pages"]["/Kids"][page_num - 1].get_object()
            media_box = page.get("/MediaBox") or page.get("/CropBox")
            if media_box:
                return float(media_box[2]), float(media_box[3])
    except Exception:
        pass
    return 612, 792


def _collect_text_candidates_on_page(pdf_path, target_page):
    """Collect ALL text-based signature candidates on a specific page.

    Returns a list of candidate dicts (not just the best one).
    """
    try:
        from pdfminer.high_level import extract_pages
        from pdfminer.layout import LTTextBox, LTTextLine, LAParams
    except ImportError:
        return []

    sign_compiled = [re.compile(p, re.IGNORECASE) for p in SIGN_PATTERNS]
    candidates = []

    try:
        for page_num, page_layout in enumerate(extract_pages(str(pdf_path), laparams=LAParams()), 1):
            if page_num != target_page:
                continue
            for element in page_layout:
                if not isinstance(element, (LTTextBox, LTTextLine)):
                    continue
                text = element.get_text().strip()
                for pattern in sign_compiled:
                    if pattern.search(text):
                        bbox = element.bbox
                        candidates.append({
                            "method": "text_placeholder",
                            "label": text[:60],
                            "page": page_num,
                            "x": bbox[0],
                            "y": bbox[1],
                            "width": min(200, bbox[2] - bbox[0]),
                            "height": max(50, bbox[3] - bbox[1]),
                        })
                        break
    except Exception as e:
        print(f"Warning: Text scan for all candidates failed: {e}", file=sys.stderr)

    return candidates


def detect_all_signature_locations_on_page(pdf_path, target_page):
    """Detect ALL signature locations on a specific page.

    Uses text placeholder scan first, then vision model.
    Returns a list of location dicts. Each has: x, y, width, height, label, method.
    """
    pdf_path = Path(pdf_path)

    # Try text-based detection first — collect all matches
    text_candidates = _collect_text_candidates_on_page(pdf_path, target_page)
    if text_candidates:
        return text_candidates

    # Vision fallback — detect all signature locations
    try:
        from scripts.vision_detect import detect_all_signatures_vision, vision_coords_to_pdf
    except ImportError:
        try:
            from vision_detect import detect_all_signatures_vision, vision_coords_to_pdf
        except ImportError:
            return []

    vision_results = detect_all_signatures_vision(str(pdf_path), target_page)
    if not vision_results:
        return []

    page_width, page_height = _get_page_dimensions(str(pdf_path), target_page)
    locations = []
    for item in vision_results:
        x, y = vision_coords_to_pdf(item["x_pct"], item["y_pct"], page_width, page_height)
        locations.append({
            "method": "vision",
            "label": item.get("label", "Signature"),
            "page": target_page,
            "x": x,
            "y": y - 25,
            "width": 200,
            "height": 50,
        })

    return locations


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
