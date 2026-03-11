"""Security utilities for API-key generation and password hashing/verification."""

import secrets
import hashlib
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

# Initialize the Argon2 hasher with OWASP recommended defaults
ph = PasswordHasher(
    memory_cost=16384,  # Uses exactly 16 MB of RAM per login instead of 64 MB
    time_cost=2,        # Runs the math 2 times to compensate for the lower RAM
    parallelism=2       # Uses 2 CPU threads to calculate it
)

def generate_raw_api_key() -> str:
    """Generates a secure, random API key for a new tenant."""
    return f"docflow_live_{secrets.token_urlsafe(32)}"

def hash_api_key(raw_api_key: str) -> str:
    """SHA-256 is safe here because 32-byte API keys cannot be brute-forced."""
    return hashlib.sha256(raw_api_key.encode()).hexdigest()

def hash_password(raw_password: str) -> str:
    """Uses Argon2id to create a memory-hard, salted hash for human passwords."""
    return ph.hash(raw_password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Safely verifies an Argon2 hash, catching the mismatch error."""
    try:
        # Note: argon2-cffi takes the hash first, then the plain password!
        return ph.verify(hashed_password, plain_password)
    except VerifyMismatchError:
        return False