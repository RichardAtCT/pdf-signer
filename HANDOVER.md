# HANDOVER.md — pdf-signer

## What You're Building

A general-purpose PDF signing tool usable by any AI agent or human. Read SPEC.md fully before writing any code.

## Your Job

Build the complete tool as specified in SPEC.md:

1. `scripts/gen_cert.py` — self-signed cert generation (run once per signer)
2. `scripts/detect_fields.py` — the 3-stage detection chain
3. `scripts/vision_detect.py` — Anthropic vision wrapper using `claude-sonnet-4-6`
4. `scripts/sign.py` — main CLI entry point
5. `requirements.txt` — all Python deps
6. `SKILL.md` — OpenClaw skill descriptor
7. `README.md` — installation and usage docs

## Key Decisions

- **Vision model:** Use `claude-sonnet-4-6` as the model string via the Anthropic Python SDK
- **Config:** All paths/identity configurable via env vars — no hardcoded names or paths
- **Cert location:** Default `~/.pdf-signer/` — create dir if missing
- **Passphrase:** Generate random 32-char alphanumeric on first run, save to `.cert-pass` (chmod 600)
- **PyHanko version:** `pyhanko>=0.21.0`
- **PDF rendering for vision:** `pdf2image` wrapping poppler's `pdftoppm`
- **Signature font:** Bundle a free script/cursive font in `assets/` (e.g. download GreatVibes or similar from Google Fonts)

## Implementation Notes

- `sign.py` is the only entry point agents need
- Detection chain runs automatically unless explicit `--page`/`--x`/`--y` flags are passed
- Keep deps minimal — only what's in the spec
- Handle missing deps gracefully (print install instructions and exit cleanly)
- All output to stdout as JSON; errors to stderr
- Test the script runs end-to-end before finishing

## When You're Done

1. Commit everything: `feat: initial pdf-signer implementation`
2. Push to origin main
3. Run: `openclaw system event --text "Done: pdf-signer skill built and pushed to GitHub" --mode now`
