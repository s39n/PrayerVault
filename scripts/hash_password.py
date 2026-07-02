"""Generate a bcrypt hash for AUTH_PASSWORD_HASH in .env"""
import base64
import getpass

import bcrypt

pw = getpass.getpass("Choose a password: ")
if pw != getpass.getpass("Repeat it: "):
    raise SystemExit("Passwords do not match.")
h = bcrypt.hashpw(pw.encode(), bcrypt.gensalt(12)).decode()
print("\nAUTH_PASSWORD_HASH=" + h)
print("\n# $-free version for Dockhand/compose env panels:")
print("AUTH_PASSWORD_HASH_B64=" + base64.b64encode(h.encode()).decode())
