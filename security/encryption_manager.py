import os
import base64
import secrets
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import hashlib

MASTER_KEY = b"nexus-wallet-super-secret-key-32bytes!!"

class EncryptionManager:
    def __init__(self):
        self.master_key = hashlib.sha256(MASTER_KEY).digest()
    
    def hash_pin(self, pin: str) -> str:
        salt = secrets.token_bytes(16)
        kdf = hashlib.pbkdf2_hmac('sha256', pin.encode(), salt, 100000)
        return base64.b64encode(salt + kdf).decode()
    
    def verify_pin(self, pin: str, stored_hash: str) -> bool:
        try:
            data = base64.b64decode(stored_hash)
            salt = data[:16]
            kdf = hashlib.pbkdf2_hmac('sha256', pin.encode(), salt, 100000)
            return secrets.compare_digest(kdf, data[16:])
        except:
            return False

encryption_manager = EncryptionManager()
