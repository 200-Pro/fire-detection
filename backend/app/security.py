import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from datetime import timezone
from threading import Lock
from fastapi import HTTPException

COOKIE = "ember_session"

def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()

def hash_password(password):
    salt = secrets.token_hex(16)
    value = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()
    return salt + ":" + value

def verify_password(password, encoded):
    salt, expected = encoded.split(":")
    value = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()
    return hmac.compare_digest(expected, value)

def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value

class RateLimiter:
    """Bounded single-process limits. Shared limiting is required for scale-out."""
    def __init__(self):
        self.entries = defaultdict(deque)
        self.lock = Lock()

    def check(self, key, count, seconds):
        with self.lock:
            self._check(key, count, seconds)

    def _check(self, key, count, seconds):
        now = time.monotonic()
        if len(self.entries) > 4096:
            self.entries = defaultdict(deque, {k:v for k,v in self.entries.items() if v and v[-1] > now-300})
        values = self.entries[key]
        while values and values[0] <= now-seconds:
            values.popleft()
        if len(values) >= count:
            raise HTTPException(429, "요청이 많습니다. 잠시 뒤 다시 시도하세요.", headers={"Retry-After": str(int(seconds))})
        values.append(now)
