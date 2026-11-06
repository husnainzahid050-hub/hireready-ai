"""Guest tokens: the client holds a random secret; the DB only stores its SHA-256 hash.

If the database leaked, the hashes couldn't be used to access sessions. Comparison uses
`hmac.compare_digest` (constant time) so response timing doesn't leak how many chars matched.
"""

import hashlib
import hmac
import secrets


def new_guest_token() -> str:
    return secrets.token_urlsafe(32)  # 32 random bytes


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_matches(token: str | None, stored_hash: str) -> bool:
    if not token:
        return False
    return hmac.compare_digest(hash_token(token), stored_hash)


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
