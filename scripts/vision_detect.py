#!/usr/bin/env python3
"""Vision model detection of signature locations in PDF pages."""

import os
import sys
import json
import base64
from pathlib import Path


def detect_signature_vision(pdf_path, dpi=150, target_page=None):
    """Render PDF pages as images and use Claude vision to find signature locations.

    If target_page is provided (1-based), only renders and checks that specific page.
    Returns a dict with detection results or None if nothing found.
    """
    try:
        from pdf2image import convert_from_path
    except ImportError:
        print("Error: 'pdf2image' package required. Install with: pip install pdf2image", file=sys.stderr)
        print("Also requires poppler: brew install poppler (macOS) or apt install poppler-utils (Linux)", file=sys.stderr)
        return None

    try:
        import anthropic
    except ImportError:
        print("Error: 'anthropic' package required. Install with: pip install anthropic", file=sys.stderr)
        return None

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Warning: ANTHROPIC_API_KEY not set, skipping vision detection.", file=sys.stderr)
        return None

    client = anthropic.Anthropic(api_key=api_key)

    try:
        if target_page is not None:
            images = convert_from_path(
                str(pdf_path), dpi=dpi, fmt="png",
                first_page=target_page, last_page=target_page,
            )
            # Re-map so enumeration starts at the target page number
            pages_and_images = [(target_page, images[0])] if images else []
        else:
            images = convert_from_path(str(pdf_path), dpi=dpi, fmt="png")
            pages_and_images = list(enumerate(images, 1))
    except Exception as e:
        print(f"Warning: Failed to render PDF pages: {e}", file=sys.stderr)
        return None

    for page_num, img in pages_and_images:
        import io
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        img_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        prompt = (
            f"This is page {page_num} of a PDF document. "
            "Identify if there is a signature line, signature box, or place where a signature should go. "
            'If yes, return a JSON object: {"found": true, "page": '
            f'{page_num}, "x_pct": <0-100>, "y_pct": <0-100>, '
            '"description": "..."} where x_pct and y_pct are the percentage position from top-left '
            'of the signature location. If no signature location found, return {"found": false}.'
        )

        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=300,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": img_b64,
                                },
                            },
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
            )
        except Exception as e:
            print(f"Warning: Vision API call failed for page {page_num}: {e}", file=sys.stderr)
            continue

        response_text = response.content[0].text.strip()

        # Extract JSON from the response
        try:
            # Try to find JSON in the response
            start = response_text.find("{")
            end = response_text.rfind("}") + 1
            if start >= 0 and end > start:
                result = json.loads(response_text[start:end])
                if result.get("found"):
                    result["page"] = page_num
                    return result
        except json.JSONDecodeError:
            continue

    return None


def detect_all_signatures_vision(pdf_path, target_page, dpi=150):
    """Render a specific PDF page and use Claude vision to find ALL signature locations.

    Returns a list of dicts with x_pct, y_pct, label for each signature location,
    or an empty list if none found.
    """
    try:
        from pdf2image import convert_from_path
    except ImportError:
        return []

    try:
        import anthropic
    except ImportError:
        return []

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return []

    client = anthropic.Anthropic(api_key=api_key)

    try:
        images = convert_from_path(
            str(pdf_path), dpi=dpi, fmt="png",
            first_page=target_page, last_page=target_page,
        )
        if not images:
            return []
    except Exception as e:
        print(f"Warning: Failed to render PDF page {target_page}: {e}", file=sys.stderr)
        return []

    import io
    img = images[0]
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    img_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

    prompt = (
        f"This is page {target_page} of a PDF document. "
        "List ALL signature boxes or lines on this page where a person should sign. "
        "For each one, provide: a short label (e.g. Purchaser 1, Seller, Witness), "
        "and the x_pct/y_pct coordinates (0-100, percentage from top-left) of the center of the signature line. "
        "Return a JSON array of objects: "
        '[{"label": "...", "x_pct": <0-100>, "y_pct": <0-100>}, ...] '
        "If no signature locations found, return an empty array []."
    )

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": img_b64,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
    except Exception as e:
        print(f"Warning: Vision API call failed for page {target_page}: {e}", file=sys.stderr)
        return []

    response_text = response.content[0].text.strip()

    try:
        start = response_text.find("[")
        end = response_text.rfind("]") + 1
        if start >= 0 and end > start:
            items = json.loads(response_text[start:end])
            return [
                item for item in items
                if isinstance(item, dict) and "x_pct" in item and "y_pct" in item
            ]
    except json.JSONDecodeError:
        pass

    return []


def vision_coords_to_pdf(x_pct, y_pct, page_width, page_height):
    """Convert percentage coordinates from vision model to PDF points.

    Vision model returns percentages from top-left.
    PDF coordinates have origin at bottom-left.
    """
    x = (x_pct / 100.0) * page_width
    y = page_height - (y_pct / 100.0) * page_height
    return x, y


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: vision_detect.py <input.pdf>", file=sys.stderr)
        sys.exit(1)

    result = detect_signature_vision(sys.argv[1])
    if result:
        print(json.dumps(result, indent=2))
    else:
        print(json.dumps({"found": False}))
