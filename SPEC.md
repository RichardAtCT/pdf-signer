# pdf-signer — Spec

## Purpose

A general-purpose command-line tool and OpenClaw agent skill for signing PDF documents. Designed to be used by any AI agent or human operator to apply digital signatures to PDFs on behalf of any configured signer. Supports cryptographic signing via X.509 certificates, automatic signature field detection, and AI-powered location detection for unstructured documents.

## Stack

- **Language:** Python 3
- **Signing library:** PyHanko (`pyhanko` package)
- **Certificate:** Self-signed X.509 cert (generated on first run via `gen_cert.py`), stored as PKCS#12 at a configurable path
- **Vision model:** `claude-sonnet-4-6` via Anthropic API (for unstructured document detection)
- **PDF rendering:** `pdf2image` + `poppler` (for converting pages to images for vision inspection)

## Project Structure

```
pdf-signer/
  SKILL.md              # OpenClaw skill descriptor
  scripts/
    sign.py             # Main signing script (entry point)
    detect_fields.py    # Signature field detection logic
    gen_cert.py         # Generate/check self-signed certificate
    vision_detect.py    # Vision model field detection
  requirements.txt
  README.md
```

## Certificate Management

`gen_cert.py` generates a self-signed X.509 cert if one doesn't exist at the configured path. Configuration via environment variables or CLI flags:

- `PDF_SIGNER_CERT_PATH` — path to .p12 cert file (default: `~/.pdf-signer/signer.p12`)
- `PDF_SIGNER_CERT_PASS` — passphrase (default: read from `~/.pdf-signer/.cert-pass`)
- `PDF_SIGNER_NAME` — signer display name (default: read from cert CN)
- `PDF_SIGNER_EMAIL` — signer email (used in cert generation)

On first run, `gen_cert.py`:
- Creates `~/.pdf-signer/` directory
- Generates a random 32-char alphanumeric passphrase, saves to `.cert-pass` (chmod 600)
- Generates a self-signed cert valid for 10 years
- Prints the cert path and fingerprint

## Signature Detection — Priority Chain

When signing a PDF, detect where to place the signature using this chain:

### 1. PyHanko Field Detection (highest priority)
Use PyHanko to check if the PDF contains existing AcroForm signature fields. If found, sign the first unsigned field. This covers formally-prepared PDFs (DocuSign exports, Adobe forms, etc.).

### 2. Text Placeholder Scan
Extract the text layer from the PDF. Search for common signature placeholder patterns (case-insensitive):
- `/s/`
- `[SIGNATURE]`, `[SIGN HERE]`
- `{{signature}}`, `{signature}`
- `________________________` (5+ underscores)
- `Signature:` followed by blank space

If found, extract the bounding box of the matched text and place the visible signature stamp at that location.

### 3. Vision Model Detection (fallback)
If no fields or text placeholders are found, render each page as an image (150 DPI, PNG) and send to `claude-sonnet-4-6` via the Anthropic API with this prompt:

> "This is page N of a PDF document. Identify if there is a signature line, signature box, or place where a signature should go. If yes, return a JSON object: {"found": true, "page": N, "x_pct": <0-100>, "y_pct": <0-100>, "description": "..."} where x_pct and y_pct are the percentage position from top-left of the signature location. If no signature location found, return {"found": false}."

Convert returned percentage coordinates to PDF point coordinates for placement.

### 4. Manual Fallback
If all detection methods fail, exit with error and instructions:
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

# Invisible signature only (cryptographic, no visual stamp)
python3 scripts/sign.py input.pdf output.pdf --invisible

# Override signer identity
python3 scripts/sign.py input.pdf output.pdf --name "Jane Smith" --email "jane@example.com"

# Use a specific cert
python3 scripts/sign.py input.pdf output.pdf --cert /path/to/signer.p12
```

## Visual Signature Appearance

The visible signature stamp renders:
- Signer name in a script/cursive style (using `GreatVibes-Regular.ttf` or similar free font bundled in `assets/`)
- Date automatically appended (e.g. "16 March 2026")
- Small "Digitally signed" label in grey beneath
- Clean appearance, no border box
- Default size: 200×50 points

If a signature image is provided via `PDF_SIGNER_IMAGE` env var or `--signature-image` flag, use it instead of text rendering.

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `PDF_SIGNER_CERT_PATH` | Path to .p12 cert | `~/.pdf-signer/signer.p12` |
| `PDF_SIGNER_CERT_PASS` | Cert passphrase | Read from `~/.pdf-signer/.cert-pass` |
| `PDF_SIGNER_NAME` | Signer display name | From cert CN |
| `PDF_SIGNER_EMAIL` | Signer email | From cert |
| `PDF_SIGNER_IMAGE` | Path to signature PNG | None (use text rendering) |
| `ANTHROPIC_API_KEY` | Required for vision detection | — |

## JSON Output

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

## SKILL.md

Write an OpenClaw-compatible SKILL.md that describes:
- What the skill does (sign PDFs on behalf of a configured signer)
- Setup (run `gen_cert.py` once, set env vars)
- How to call `sign.py`
- The detection chain
- Example usage

## README.md

Write a clear README covering:
- What it does
- Installation (`pip install -r requirements.txt`, poppler dependency note)
- First-run setup (`python3 scripts/gen_cert.py`)
- Configuration (env vars table)
- Usage examples
- How the detection chain works
- Contributing / licence (MIT)

---

## Initials Feature (v1.1)

### Overview

Support placing initials stamps on documents — smaller stamps used for page-by-page acknowledgement or mid-document initial boxes, in addition to (or instead of) a full signature.

### Initials Stamp Appearance

- Size: 80×30 points (vs 200×50 for full signature)
- Content: signer's initials (e.g. "RA") in the same cursive font
- No date, no "Digitally signed" label — just the initials
- Auto-derive from `PDF_SIGNER_NAME`: take first letter of each word (e.g. "PDF Signer" → "RA")
- Override via `PDF_SIGNER_INITIALS` env var or `--initials-text` flag
- Custom image via `PDF_SIGNER_INITIALS_IMAGE` env var or `--initials-image` flag

### CLI Flags

```bash
# Place initials at detected/specified location instead of full signature
python3 scripts/sign.py input.pdf output.pdf --initials

# Place initials on every page at bottom-left corner, then sign
python3 scripts/sign.py input.pdf output.pdf --initials-all-pages

# Use custom initials text
python3 scripts/sign.py input.pdf output.pdf --initials --initials-text "RA"

# Use custom initials image
python3 scripts/sign.py input.pdf output.pdf --initials --initials-image /path/to/initials.png
```

### Detection for Initials

Extend `detect_fields.py` with `detect_initials_locations()`:
- Scan for patterns: `[INITIALS]`, `[INIT]`, `/i/`, `Initials:` followed by whitespace
- Return a list of locations (all matches, not just the first)
- Vision fallback: ask the model to identify ALL initial boxes on the page

### Multi-placement Flow

When `--initials-all-pages` is set:
1. Place initials stamp at bottom-left of every page (position: x=20, y=20, consistent)
2. Then apply the single cryptographic signature (to avoid multiple signing events)

When initials placeholders are detected:
1. Collect ALL detected initials locations across all pages
2. Place initials stamps at each location
3. Apply single cryptographic signature

### Output

Include initials placement in JSON output:
```json
{
  "success": true,
  "output": "/path/to/signed.pdf",
  "detection_method": "text_placeholder",
  "signature_page": 5,
  "signature_location": {"x": 400, "y": 100},
  "initials_placed": [
    {"page": 1, "x": 20, "y": 20},
    {"page": 2, "x": 20, "y": 20}
  ]
}
```
