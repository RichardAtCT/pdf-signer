# pdf-signer — Spec

## Purpose

An OpenClaw agent skill that enables AI agents (Friday and others) to sign PDF documents on behalf of PDF Signer. The skill handles the full pipeline: detecting where a signature is needed, placing it correctly, and producing a signed output PDF.

## Stack

- **Language:** Python 3
- **Signing library:** PyHanko (`pyhanko` package)
- **Certificate:** Self-signed X.509 cert for PDF Signer (generated on first run, stored in `~/~/.pdf-signer/signer.p12`)
- **Vision model:** `claude-3-5-sonnet-20241022` via Anthropic API (for unstructured document detection)
- **PDF rendering:** `pdf2image` + `poppler` (for converting pages to images for vision inspection)

## Skill Structure

```
~/.openclaw/skills/pdf-signer/
  SKILL.md              # OpenClaw skill descriptor
  scripts/
    sign.py             # Main signing script
    detect_fields.py    # Signature field detection logic
    gen_cert.py         # Generate/check self-signed certificate
    vision_detect.py    # Vision model field detection
  requirements.txt
  README.md
```

## Certificate

On first use, `gen_cert.py` checks for `~/~/.pdf-signer/signer.p12`. If missing, generates a self-signed cert:
- Common Name: PDF Signer
- Email: signer@example.com
- Valid: 10 years
- Stored as PKCS#12 (.p12), passphrase in `~/~/.pdf-signer/.cert-pass`

## Signature Detection — Priority Chain

When signing a PDF, detect where to place the signature using this chain:

### 1. PyHanko Field Detection (highest priority)
Use PyHanko to check if the PDF contains existing AcroForm signature fields. If found, sign the first unsigned field. This covers formally-prepared PDFs (DocuSign exports, Adobe forms, etc.).

### 2. Text Placeholder Scan
Extract the text layer from the PDF (using `pdfminer.six` or PyHanko's reader). Search for common signature placeholder patterns (case-insensitive):
- `/s/`
- `[SIGNATURE]`, `[SIGN HERE]`
- `{{signature}}`, `{signature}`
- `________________________` (5+ underscores)
- `Signature:` followed by blank space

If found, extract the bounding box of the text, place the visible signature stamp just above/at that location.

### 3. Vision Model Detection (fallback)
If no fields or text placeholders are found, render each page as an image (150 DPI, PNG) and send to `claude-sonnet-4-6` with this prompt:

> "This is page N of a PDF document. Identify if there is a signature line, signature box, or place where a signature should go. If yes, return a JSON object: {"found": true, "page": N, "x_pct": <0-100>, "y_pct": <0-100>, "description": "..."} where x_pct and y_pct are the percentage position from top-left of the signature location. If no signature location found, return {"found": false}."

Use the returned coordinates (converting percentage to PDF point coordinates) to place the signature.

### 4. Manual Fallback
If all three detection methods fail, exit with a clear error message and instructions for the calling agent:
```
No signature location detected. Re-run with explicit placement:
  sign.py input.pdf output.pdf --page 1 --x 400 --y 100
  sign.py input.pdf output.pdf --position last-page-bottom-right
```

## Signing Script CLI

```bash
# Auto-detect signature location
python3 scripts/sign.py input.pdf output.pdf

# Explicit page + coordinates (PDF points, origin bottom-left)
python3 scripts/sign.py input.pdf output.pdf --page 1 --x 400 --y 100 --width 200 --height 50

# Named positions
python3 scripts/sign.py input.pdf output.pdf --position last-page-bottom-right
python3 scripts/sign.py input.pdf output.pdf --position last-page-bottom-left

# Invisible signature only (no visual stamp, just cryptographic)
python3 scripts/sign.py input.pdf output.pdf --invisible
```

## Visual Signature Appearance

The visible signature stamp should render:
- Signature text in a cursive/script style (using a signature font, e.g. `GreatVibes-Regular.ttf` or similar free font)
- Name: "PDF Signer"
- Date: automatically appended (e.g. "16 March 2026")
- Small "Digitally signed" label in grey beneath
- No border box — clean, natural appearance
- Approximate size: 200×50 points

If a signature image (`~/~/.pdf-signer/signature.png`) exists, use it instead of the text rendering.

## Environment / Config

Credentials and paths read from environment or defaults:
- `RICHARD_CERT_PATH` — override cert path (default: `~/~/.pdf-signer/signer.p12`)
- `RICHARD_CERT_PASS` — override cert passphrase (default: read from `.cert-pass` file)
- `ANTHROPIC_API_KEY` — required for vision detection fallback

## SKILL.md

Write an OpenClaw-compatible SKILL.md that describes:
- When to use this skill (agent receives a PDF to sign)
- How to call the script
- The detection chain (so agents understand what to expect)
- Example usage

## README.md

Write a clear README covering:
- Installation (`pip install -r requirements.txt`, poppler dependency)
- First-run cert generation
- Usage examples
- How the detection chain works

## Output

The script should print a JSON result to stdout:
```json
{
  "success": true,
  "output": "/path/to/signed.pdf",
  "detection_method": "pyhanko_field | text_placeholder | vision | manual",
  "signature_page": 1,
  "signature_location": {"x": 400, "y": 100}
}
```

On error:
```json
{
  "success": false,
  "error": "No signature location detected. Use --page and --x/--y flags.",
  "detection_method": null
}
```
