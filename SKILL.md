# pdf-signer

**Type:** tool
**Trigger:** Agent receives a PDF document that needs to be digitally signed.

## Description

Signs PDF documents on behalf of a configured signer using a self-signed X.509 certificate. Automatically detects where to place the signature using a 3-stage detection chain, then applies a cryptographic digital signature with an optional visible stamp.

## Setup

1. Install dependencies: `pip install -r requirements.txt`
2. Install poppler (for vision fallback): `brew install poppler` (macOS) or `apt install poppler-utils` (Linux)
3. Generate a certificate (or let it auto-generate on first run):
   ```bash
   python3 scripts/gen_cert.py
   ```
4. Set environment variables as needed (see below)

## Detection Chain

The skill tries three methods in order to find the signature location:

1. **AcroForm fields** — Checks for existing PDF signature form fields (DocuSign exports, Adobe forms). Signs the first unsigned field.
2. **Text placeholders** — Scans the text layer for patterns like `/s/`, `[SIGNATURE]`, `[SIGN HERE]`, `{{signature}}`, underscores, or `Signature:` labels.
3. **Vision model** — Renders pages as images and uses `claude-sonnet-4-6` to visually identify signature lines or boxes.

If all three fail, the script exits with an error and instructions for explicit placement.

## Usage

```bash
# Auto-detect signature location
python3 scripts/sign.py input.pdf output.pdf

# Explicit coordinates (PDF points, origin bottom-left)
python3 scripts/sign.py input.pdf output.pdf --page 1 --x 400 --y 100

# Named position shortcuts
python3 scripts/sign.py input.pdf output.pdf --position last-page-bottom-right
python3 scripts/sign.py input.pdf output.pdf --position last-page-bottom-left

# Invisible signature (cryptographic only, no visual stamp)
python3 scripts/sign.py input.pdf output.pdf --invisible

# Override signer identity
python3 scripts/sign.py input.pdf output.pdf --name "Jane Smith" --email "jane@example.com"

# Use a specific cert
python3 scripts/sign.py input.pdf output.pdf --cert /path/to/signer.p12

# Use a signature image
python3 scripts/sign.py input.pdf output.pdf --signature-image /path/to/signature.png
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

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `PDF_SIGNER_CERT_PATH` | Path to .p12 cert | `~/.pdf-signer/signer.p12` |
| `PDF_SIGNER_CERT_PASS` | Cert passphrase | Read from `~/.pdf-signer/.cert-pass` |
| `PDF_SIGNER_NAME` | Signer display name | From cert CN |
| `PDF_SIGNER_EMAIL` | Signer email | From cert |
| `PDF_SIGNER_IMAGE` | Path to signature PNG | None (use text rendering) |
| `ANTHROPIC_API_KEY` | Required for vision detection fallback | — |

## Notes

- On first run, a self-signed certificate is generated automatically at `~/.pdf-signer/signer.p12`
- The certificate is valid for 10 years
- If a signature image is provided via `PDF_SIGNER_IMAGE` or `--signature-image`, it is used as the visible stamp
