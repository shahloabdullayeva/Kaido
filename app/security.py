import base64
import hashlib
import hmac
import os
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import config

SCRYPT_N = 16384
SCRYPT_R = 8
SCRYPT_P = 1
KEY_LEN = 64


def hash_password(password):
    salt = os.urandom(16)
    derived = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=KEY_LEN, maxmem=64 * 1024 * 1024)
    return "scrypt${}${}${}${}${}".format(
        SCRYPT_N, SCRYPT_R, SCRYPT_P,
        base64.b64encode(salt).decode(),
        base64.b64encode(derived).decode(),
    )


def verify_password(password, stored):
    try:
        scheme, n, r, p, salt_b64, hash_b64 = str(stored).split("$")
        if scheme != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        derived = hashlib.scrypt(
            password.encode(), salt=salt, n=int(n), r=int(r), p=int(p),
            dklen=len(expected), maxmem=64 * 1024 * 1024,
        )
        return hmac.compare_digest(expected, derived)
    except (ValueError, TypeError):
        return False


DUMMY_HASH = hash_password("placeholder-for-constant-time-compare")


def burn_password_time():
    verify_password("not-the-password", DUMMY_HASH)


def random_token(length=32):
    return secrets.token_urlsafe(length)


def random_code():
    return f"{secrets.randbelow(1000000):06d}"


def sha256(value):
    if isinstance(value, str):
        value = value.encode()
    return hashlib.sha256(value).digest()


def _aes_key():
    return hashlib.scrypt(
        config.ENCRYPTION_KEY.encode(), salt=b"fleet-integration-credentials",
        n=16384, r=8, p=1, dklen=32, maxmem=64 * 1024 * 1024,
    )


def encrypt(plaintext):
    if plaintext is None:
        return None
    nonce = os.urandom(12)
    box = AESGCM(_aes_key())
    return nonce + box.encrypt(nonce, plaintext.encode(), None)


def decrypt(blob):
    if not blob:
        return None
    blob = bytes(blob)
    box = AESGCM(_aes_key())
    return box.decrypt(blob[:12], blob[12:], None).decode()


def csrf_token(secret):
    return base64.urlsafe_b64encode(
        hmac.new(config.SECRET_KEY.encode(), secret.encode(), hashlib.sha256).digest()
    ).decode().rstrip("=")


def csrf_matches(secret, submitted):
    if not secret or not submitted:
        return False
    return hmac.compare_digest(csrf_token(secret), str(submitted))


def mask_token(value):
    if not value:
        return "not set"
    tail = value[-4:] if len(value) > 4 else "****"
    return f"••••{tail}"
