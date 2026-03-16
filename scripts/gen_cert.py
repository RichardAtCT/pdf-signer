#!/usr/bin/env python3
"""Generate a self-signed X.509 certificate for PDF signing."""

import os
import sys
import string
import secrets
from pathlib import Path
from datetime import datetime, timedelta, timezone

DEFAULT_CERT_DIR = Path.home() / ".openclaw" / "workspace" / ".certs"
DEFAULT_CERT_PATH = DEFAULT_CERT_DIR / "signer.p12"
DEFAULT_PASS_PATH = DEFAULT_CERT_DIR / ".cert-pass"

COMMON_NAME = "PDF Signer"
EMAIL = "signer@example.com"
VALIDITY_YEARS = 10


def generate_passphrase(length: int = 32) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def ensure_cert(
    cert_path=None,
    pass_path=None,
):
    """Ensure the signing certificate exists. Generate if missing.

    Returns (cert_path, passphrase).
    """
    cert_path = Path(os.environ.get("RICHARD_CERT_PATH", cert_path or DEFAULT_CERT_PATH))
    pass_path = pass_path or DEFAULT_PASS_PATH

    if cert_path.exists():
        passphrase = os.environ.get("RICHARD_CERT_PASS")
        if not passphrase:
            if pass_path.exists():
                passphrase = pass_path.read_text().strip()
            else:
                print("Error: Certificate exists but no passphrase found.", file=sys.stderr)
                sys.exit(1)
        return cert_path, passphrase

    # Generate new cert
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
    except ImportError:
        print("Error: 'cryptography' package required. Install with: pip install cryptography", file=sys.stderr)
        sys.exit(1)

    print(f"Generating self-signed certificate for {COMMON_NAME}...", file=sys.stderr)

    # Generate RSA key
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    # Build certificate
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, COMMON_NAME),
        x509.NameAttribute(NameOID.EMAIL_ADDRESS, EMAIL),
    ])

    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=365 * VALIDITY_YEARS))
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=True,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )

    # Generate passphrase and save
    passphrase = generate_passphrase()

    cert_path.parent.mkdir(parents=True, exist_ok=True)

    # Write PKCS#12
    from cryptography.hazmat.primitives.serialization.pkcs12 import serialize_key_and_certificates
    p12_data = serialize_key_and_certificates(
        name=COMMON_NAME.encode(),
        key=key,
        cert=cert,
        cas=None,
        encryption_algorithm=serialization.BestAvailableEncryption(passphrase.encode()),
    )
    cert_path.write_bytes(p12_data)
    os.chmod(cert_path, 0o600)

    # Write passphrase
    pass_path.write_text(passphrase)
    os.chmod(pass_path, 0o600)

    print(f"Certificate saved to {cert_path}", file=sys.stderr)
    print(f"Passphrase saved to {pass_path}", file=sys.stderr)

    return cert_path, passphrase


if __name__ == "__main__":
    cert_path, _ = ensure_cert()
    print(f"Certificate ready: {cert_path}", file=sys.stderr)
