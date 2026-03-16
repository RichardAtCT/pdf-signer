# HANDOVER.md — pdf-signer

## What You're Building

An OpenClaw agent skill for signing PDF documents. Read SPEC.md fully before writing any code.

## Your Job

Build the complete skill as specified in SPEC.md. This means:

1. `scripts/gen_cert.py` — self-signed cert generation (run once)
2. `scripts/detect_fields.py` — the 3-stage detection chain
3. `scripts/vision_detect.py` — Anthropic vision wrapper
4. `scripts/sign.py` — main CLI entry point
5. `requirements.txt` — all Python deps
6. `SKILL.md` — OpenClaw skill descriptor
7. `README.md` — installation and usage docs

## Key Decisions

- **Vision model:** Use `claude-3-5-sonnet-20241022` via the Anthropic Python SDK (`anthropic` package). Pass rendered page images as base64. The model name in SPEC says `claude-sonnet-4-6` — use `claude-sonnet-4-6` as the model string.
- **Cert location:** `~/~/.pdf-signer/` — create dir if missing
- **Passphrase:** Generate a random 32-char alphanumeric passphrase on first run, save to `.cert-pass` (chmod 600)
- **PyHanko version:** Use latest stable (`pyhanko>=0.21.0`)
- **PDF rendering for vision:** Use `pdf2image` which wraps poppler's `pdftoppm`

## Implementation Notes

- The sign.py script should be the only entry point agents need
- Detection chain runs automatically unless `--page`/`--x`/`--y` are specified
- Keep dependencies minimal — don't add anything not in the spec
- All scripts should handle missing deps gracefully (print install instructions)
- Test that the script runs end-to-end before finishing

## When You're Done

1. Commit everything with message: `feat: initial pdf-signer skill implementation`
2. Push to origin main
3. Run this to notify:
   `openclaw system event --text "Done: pdf-signer skill built and pushed to GitHub" --mode now`
