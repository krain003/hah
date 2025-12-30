import os
import base64
import secrets
import hashlib
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from config import settings  # твой config

class EncryptionManager:
    def __init__(self):
        self.master_key = hashlib.sha256(settings.MASTER_KEY.encode()).digest()
    
    def hash_pin(self, pin: str) -> str:
        salt = secrets.token_bytes(16)
        kdf = hashlib.pbkdf2_hmac('sha256', pin.encode(), salt, 100000)
        return base64.b64encode(salt + kdf).decode()
    
    def verify_pin(self, pin: str, stored_hash: str) -> bool:
        try:
            data = base64.b64decode(stored_hash)
            salt, stored_key = data[:16], data[16:]
            kdf = hashlib.pbkdf2_hmac('sha256', pin.encode(), salt, 100000)
            return secrets.compare_digest(kdf, stored_key)
        except:
            return False
    
    def encrypt_private_key(self, private_key: str) -> str:
        aesgcm = AESGCM(self.master_key)
        nonce = os.urandom(12)
        ct = aesgcm.encrypt(nonce, private_key.encode(), None)
        return base64.b64encode(nonce + ct).decode()

encryption_manager = EncryptionManager()
