# pdf-signer

A general-purpose command-line tool and OpenClaw agent skill for signing PDF documents. Supports cryptographic signing via self-signed X.509 certificates, automatic signature field detection, and AI-powered location detection for unstructured documents.

## Features

- **3-stage signature detection** — AcroForm fields → text placeholders → Claude vision model
- **Configurable signer** — identity set via environment variables or CLI flags
- **Visible stamp** — renders signer name + date on the document
- **JSON output** — machine-readable results for agent integration
- **Invisible signing** — cryptographic-only option (no visual stamp)

## Installation

```bash
pip install -r requirements.txt
```

poppler is required for the vision detection fallback:

```bash
# macOS
brew install poppler

# Linux
apt install poppler-utils
```

## First Run

On first use, a self-signed X.509 certificate is generated automatically at `~/.pdf-signer/signer.p12`. To generate it manually (recommended to set identity):

```bash
PDF_SIGNER_NAME="Jane Smith" PDF_SIGNER_EMAIL="jane@example.com" python3 scripts/gen_cert.py
```

This creates:
- `~/.pdf-signer/signer.p12` — PKCS#12 certificate (chmod 600)
- `~/.pdf-signer/.cert-pass` — random 32-char passphrase (chmod 600)

## Configuration

| Variable | Description | Default |
|---|---|---|
| `PDF_SIGNER_CERT_PATH` | Path to .p12 cert file | `~/.pdf-signer/signer.p12` |
| `PDF_SIGNER_CERT_PASS` | Cert passphrase | Read from `~/.pdf-signer/.cert-pass` |
| `PDF_SIGNER_NAME` | Signer display name | From cert CN |
| `PDF_SIGNER_EMAIL` | Signer email (used at cert generation) | — |
| `PDF_SIGNER_IMAGE` | Path to signature PNG image | None (uses text rendering) |
| `ANTHROPIC_API_KEY` | Required for vision detection fallback | — |

## Usage

```bash
# Auto-detect signature location
python3 scripts/sign.py input.pdf signed.pdf

# Explicit coordinates (PDF points, origin bottom-left)
python3 scripts/sign.py input.pdf signed.pdf --page 1 --x 400 --y 100 --width 200 --height 50

# Named positions
python3 scripts/sign.py input.pdf signed.pdf --position last-page-bottom-right
python3 scripts/sign.py input.pdf signed.pdf --position last-page-bottom-left

# Invisible signature (cryptographic only, no visual stamp)
python3 scripts/sign.py input.pdf signed.pdf --invisible

# Override signer identity at runtime
python3 scripts/sign.py input.pdf signed.pdf --name "Jane Smith" --email "jane@example.com"

# Use a specific cert
python3 scripts/sign.py input.pdf signed.pdf --cert /path/to/signer.p12

# Use a signature image instead of text rendering
python3 scripts/sign.py input.pdf signed.pdf --signature-image /path/to/sig.png
```

## Detection Chain

When no explicit coordinates are provided, the tool tries three methods in order:

1. **PyHanko AcroForm fields** — checks for existing unsigned signature form fields (DocuSign exports, Adobe Acrobat forms). Signs the first unsigned field found.

2. **Text placeholder scan** — searches the PDF text layer for common patterns:
   - `/s/`
   - `[SIGNATURE]`, `[SIGN HERE]`
   - `{{signature}}`, `{signature}`
   - `________________________` (5+ underscores)
   - `Signature:` followed by whitespace

3. **Vision model (Claude)** — renders each page as a PNG image at 150 DPI and sends to `claude-sonnet-4-6` to visually identify signature lines or boxes. Requires `ANTHROPIC_API_KEY`.

If all three fail, the script exits with an error and instructions for explicit placement.

## Output

JSON is printed to stdout:

```json
{
  "success": true,
  "output": "/path/to/signed.pdf",
  "detection_method": "pyhanko_field | text_placeholder | vision | manual",
  "signature_page": 1,
  "signature_location": {"x": 400.0, "y": 100.0}
}
```

On failure:

```json
{
  "success": false,
  "error": "No signature location detected. Use --page and --x/--y flags.",
  "detection_method": null
}
```

## Standalone detection

```bash
# Test detection without signing
python3 scripts/detect_fields.py input.pdf

# Test vision detection only
python3 scripts/vision_detect.py input.pdf
```

## Licence

MIT
