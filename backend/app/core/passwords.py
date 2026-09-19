import hashlib
import hmac
import secrets


_ALGORITHM = "pbkdf2_sha256"
_ITERATIONS = 600_000
_MAX_VERIFY_ITERATIONS = 2_000_000
_SALT_BYTES = 16
_DIGEST_BYTES = 32
_MAX_PASSWORD_BYTES = 1024


def hash_password(password: str) -> str:
    """Create a salted PBKDF2 hash for storage in UserAccount.password_hash."""
    if not isinstance(password, str):
        raise ValueError("password must be a string")
    encoded = password.encode("utf-8")
    if not encoded or len(encoded) > _MAX_PASSWORD_BYTES:
        raise ValueError("password length is invalid")
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256", encoded, salt, _ITERATIONS, dklen=_DIGEST_BYTES
    )
    return f"{_ALGORITHM}${_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Return false for malformed hashes without exposing the password."""
    if not isinstance(password, str) or not isinstance(stored_hash, str):
        return False
    encoded = password.encode("utf-8")
    if not encoded or len(encoded) > _MAX_PASSWORD_BYTES:
        return False
    try:
        algorithm, iterations_text, salt_text, digest_text = stored_hash.split("$")
        if algorithm != _ALGORITHM or not iterations_text.isascii():
            return False
        iterations = int(iterations_text)
        if not 1 <= iterations <= _MAX_VERIFY_ITERATIONS:
            return False
        salt = bytes.fromhex(salt_text)
        digest = bytes.fromhex(digest_text)
        if len(salt) != _SALT_BYTES or len(digest) != _DIGEST_BYTES:
            return False
    except (ValueError, TypeError):
        return False

    candidate = hashlib.pbkdf2_hmac(
        "sha256", encoded, salt, iterations, dklen=_DIGEST_BYTES
    )
    return hmac.compare_digest(candidate, digest)
