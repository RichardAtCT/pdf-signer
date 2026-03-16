# pdf-signer

**Type:** tool
**Trigger:** Agent receives a PDF document that needs to be signed by PDF Signer.

## Description

Signs PDF documents on behalf of PDF Signer using a self-signed X.509 certificate. The skill automatically detects where to place the signature using a 3-stage detection chain, then applies a cryptographic digital signature with a visible stamp.

## Detection Chain

The skill tries three methods in order to find the signature location:

1. **AcroForm fields** — Checks for existing PDF signature form fields (DocuSign exports, Adobe forms). Signs the first unsigned field.
2. **Text placeholders** — Scans the text layer for patterns like `/s/`, `[SIGNATURE]`, `[SIGN HERE]`, `{{signature}}`, underscores, or `Signature:` labels.
3. **Vision model** — Renders pages as images and uses Claude to visually identify signature lines or boxes.

If all three fail, the script exits with an error and instructions for explicit placement.

## Usage

```bash
# Auto-detect signature location
python3 ~/.openclaw/skills/pdf-signer/scripts/sign.py input.pdf output.pdf

# Explicit coordinates (PDF points, origin bottom-left)
python3 ~/.openclaw/skills/pdf-signer/scripts/sign.py input.pdf output.pdf --page 1 --x 400 --y 100

# Named position shortcuts
python3 ~/.openclaw/skills/pdf-signer/scripts/sign.py input.pdf output.pdf --position last-page-bottom-right
python3 ~/.openclaw/skills/pdf-signer/scripts/sign.py input.pdf output.pdf --position last-page-bottom-left

# Invisible signature (cryptographic only, no visual stamp)
python3 ~/.openclaw/skills/pdf-signer/scripts/sign.py input.pdf output.pdf --invisible
```

## Output

The script prints a JSON object to stdout:

```json
{
  "success": true,
  "output": "/path/to/signed.pdf",
  "detection_method": "pyhanko_field",
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

## Requirements

- Python 3
- Dependencies: `pip install -r ~/.openclaw/skills/pdf-signer/requirements.txt`
- poppler (for vision fallback): `brew install poppler` (macOS) or `apt install poppler-utils` (Linux)
- `ANTHROPIC_API_KEY` environment variable (only needed for vision detection fallback)

## Notes

- On first run, a self-signed certificate is generated automatically at `~/~/.pdf-signer/signer.p12`
- If `~/~/.pdf-signer/signature.png` exists, it will be used as the visible signature image
- The certificate is valid for 10 years
