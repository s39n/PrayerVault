"""Generate a bcrypt hash for AUTH_PASSWORD_HASH in .env"""
import getpass

import bcrypt

pw = getpass.getpass("Choose a password: ")
if pw != getpass.getpass("Repeat it: "):
    raise SystemExit("Passwords do not match.")
print("\nAUTH_PASSWORD_HASH=" + bcrypt.hashpw(pw.encode(), bcrypt.gensalt(12)).decode())
