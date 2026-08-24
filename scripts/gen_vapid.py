"""Generate a VAPID key pair for web push.

Run once, then put the two printed lines into your .env / Dockhand env panel:

    python scripts/gen_vapid.py

VAPID_PUBLIC_KEY is safe to expose (the browser needs it). Keep VAPID_PRIVATE_KEY
secret — never commit it.
"""
import base64

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid01


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def main() -> None:
    v = Vapid01()
    v.generate_keys()
    public = v.public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    private = v.private_key.private_numbers().private_value.to_bytes(32, "big")
    print("VAPID_PUBLIC_KEY=" + _b64u(public))
    print("VAPID_PRIVATE_KEY=" + _b64u(private))
    print("# Also set VAPID_SUBJECT=mailto:you@yourchurch.org")


if __name__ == "__main__":
    main()
