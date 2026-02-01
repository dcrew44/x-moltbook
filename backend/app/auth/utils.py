import hashlib
import secrets


def generate_token() -> str:
    """Generate a secure session token with xmolt_ prefix."""
    random_bytes = secrets.token_bytes(32)
    hex_string = random_bytes.hex()
    return f"xmolt_{hex_string}"


def hash_token(token: str) -> str:
    """Hash a token using SHA-256."""
    return hashlib.sha256(token.encode()).hexdigest()


def extract_token(authorization: str) -> str | None:
    """Extract token from Authorization header."""
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None
