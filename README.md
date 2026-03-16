# pdf-signer

An OpenClaw agent skill for signing PDF documents on behalf of PDF Signer.

## Installation

### Dependencies

```bash
pip install -r requirements.txt
```

### poppler (required for vision detection fallback)

**macOS:**
```bash
brew install poppler
```

**Linux:**
```bash
apt install poppler-utils
```

## First Run

On first use, a self-signed X.509 certificate is generated automatically:

- **Certificate:** `~/~/.pdf-signer/signer.p12`
- **Passphrase:** `~/~/.pdf-signer/.cert-pass` (random 32-char, chmod 600)
- **Common Name:** PDF Signer
- **Valid:** 10 years

To generate the certificate manually:

```bash
python3 scripts/gen_cert.py
```

## Usage

### Auto-detect signature location

```bash
python3 scripts/sign.py input.pdf signed.pdf
```

### Explicit coordinates

```bash
python3 scripts/sign.py input.pdf signed.pdf --page 1 --x 400 --y 100 --width 200 --height 50
```

### Named positions

```bash
python3 scripts/sign.py input.pdf signed.pdf --position last-page-bottom-right
python3 scripts/sign.py input.pdf signed.pdf --position last-page-bottom-left
```

### Invisible signature (cryptographic only)

```bash
python3 scripts/sign.py input.pdf signed.pdf --invisible
```

## Detection Chain

When no explicit coordinates are provided, the script tries three methods in order:

1. **PyHanko AcroForm fields** — Checks for existing signature form fields in the PDF (DocuSign exports, Adobe forms, etc.). Signs the first unsigned field found.

2. **Text placeholder scan** — Uses pdfminer.six to search the text layer for common signature patterns:
   - `/s/`
   - `[SIGNATURE]`, `[SIGN HERE]`
   - `{{signature}}`, `{signature}`
   - `________________________` (5+ underscores)
   - `Signature:` followed by blank space

3. **Vision model** — Renders each page as a PNG image (150 DPI) and sends to Claude for visual identification of signature lines or boxes.

If all three methods fail, the script exits with an error and explicit placement instructions.

## Output

The script prints JSON to stdout:

```json
{
  "success": true,
  "output": "/path/to/signed.pdf",
  "detection_method": "pyhanko_field | text_placeholder | vision | manual",
  "signature_page": 1,
  "signature_location": {"x": 400, "y": 100}
}
```

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `RICHARD_CERT_PATH` | Override certificate path | `~/~/.pdf-signer/signer.p12` |
| `RICHARD_CERT_PASS` | Override certificate passphrase | Read from `.cert-pass` file |
| `ANTHROPIC_API_KEY` | Required for vision detection fallback | — |

## Visual Signature

The visible signature stamp shows:

- Name: "PDF Signer"
- Date (auto-appended)
- "Digitally signed" label

If `~/~/.pdf-signer/signature.png` exists, it is used as the signature image instead.
