"""
NEXUS WALLET - Encryption Manager
Military-grade encryption for private keys and sensitive data
"""

import os
import base64
import hashlib
import secrets
from typing import Tuple, Optional
from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from cryptography.hazmat.backends import default_backend
import nacl.secret
import nacl.utils
from nacl.pwhash import argon2id
import structlog

logger = structlog.get_logger()


class EncryptionManager:
    """
    Multi-layer encryption manager for sensitive data
    """

    def __init__(self):
        self._backend = default_backend()
        self._master_key = self._derive_master_key()

    def _derive_master_key(self) -> bytes:
        """Derive master key from environment or defaults"""
        master_secret = os.getenv("SECURITY_MASTER_KEY", "nexus-wallet-super-secret-key-32")
        salt = os.getenv("SECURITY_ENCRYPTION_SALT", "nexus-salt-16byte")

        kdf = Scrypt(
            salt=salt.encode()[:16],
            length=32,
            n=2**14,
            r=8,
            p=1,
            backend=self._backend
        )
        return kdf.derive(master_secret.encode())

    def _generate_key_from_pin(self, pin: str, salt: bytes) -> bytes:
        """Generate encryption key from PIN using Argon2id"""
        # Ensure salt is exactly 16 bytes for Argon2id
        if len(salt) < 16:
            salt = salt + b'\x00' * (16 - len(salt))
        elif len(salt) > 16:
            salt = salt[:16]
            
        return argon2id.kdf(
            size=32,
            password=pin.encode(),
            salt=salt,
            opslimit=argon2id.OPSLIMIT_MODERATE,
            memlimit=argon2id.MEMLIMIT_MODERATE
        )

    def encrypt_private_key(self, private_key: str, user_password: Optional[str] = None) -> str:
        """
        Encrypt private key with multiple layers
        Layer 1: AES-256-GCM with master key
        Layer 2: NaCl SecretBox
        """
        data = private_key.encode()

        # Layer 1: Master key encryption (AES-256-GCM)
        nonce1 = secrets.token_bytes(12)
        cipher = Cipher(
            algorithms.AES(self._master_key),
            modes.GCM(nonce1),
            backend=self._backend
        )
        encryptor = cipher.encryptor()
        ciphertext = encryptor.update(data) + encryptor.finalize()
        tag = encryptor.tag

        # Combine: nonce + tag + ciphertext
        layer1_data = nonce1 + tag + ciphertext

        # Layer 2: NaCl SecretBox
        box = nacl.secret.SecretBox(self._master_key)
        encrypted = box.encrypt(layer1_data)

        return base64.b64encode(encrypted).decode()

    def decrypt_private_key(self, encrypted_data: str, user_password: Optional[str] = None) -> str:
        """Decrypt private key"""
        try:
            data = base64.b64decode(encrypted_data)

            # Layer 2: NaCl SecretBox decrypt
            box = nacl.secret.SecretBox(self._master_key)
            layer1_data = box.decrypt(data)

            # Layer 1: AES-256-GCM decrypt
            nonce1 = layer1_data[:12]
            tag = layer1_data[12:28]
            ciphertext = layer1_data[28:]

            cipher = Cipher(
                algorithms.AES(self._master_key),
                modes.GCM(nonce1, tag),
                backend=self._backend
            )
            decryptor = cipher.decryptor()
            plaintext = decryptor.update(ciphertext) + decryptor.finalize()

            return plaintext.decode()

        except Exception as e:
            logger.error("Decryption failed", error=str(e))
            raise ValueError("Failed to decrypt private key")

    def encrypt_mnemonic(self, mnemonic: str, pin: str) -> str:
        """Encrypt mnemonic with user PIN"""
        # Generate salt (16 bytes for Argon2id)
        salt = secrets.token_bytes(16)
        key = self._generate_key_from_pin(pin, salt)
        nonce = secrets.token_bytes(12)

        cipher = Cipher(
            algorithms.AES(key),
            modes.GCM(nonce),
            backend=self._backend
        )
        encryptor = cipher.encryptor()
        ciphertext = encryptor.update(mnemonic.encode()) + encryptor.finalize()
        tag = encryptor.tag

        # Combine: salt (16) + nonce (12) + tag (16) + ciphertext
        result = salt + nonce + tag + ciphertext
        return base64.b64encode(result).decode()

    def decrypt_mnemonic(self, encrypted_mnemonic: str, pin: str) -> str:
        """Decrypt mnemonic with user PIN"""
        try:
            data = base64.b64decode(encrypted_mnemonic)

            # Extract components
            salt = data[:16]
            nonce = data[16:28]
            tag = data[28:44]
            ciphertext = data[44:]

            key = self._generate_key_from_pin(pin, salt)

            cipher = Cipher(
                algorithms.AES(key),
                modes.GCM(nonce, tag),
                backend=self._backend
            )
            decryptor = cipher.decryptor()
            plaintext = decryptor.update(ciphertext) + decryptor.finalize()

            return plaintext.decode()

        except Exception as e:
            logger.error("Mnemonic decryption failed", error=str(e))
            raise ValueError("Invalid PIN or corrupted data")

    def hash_pin(self, pin: str) -> str:
        """Hash PIN for secure storage"""
        salt = secrets.token_bytes(16)
        
        hash_bytes = argon2id.kdf(
            size=32,
            password=pin.encode(),
            salt=salt,
            opslimit=argon2id.OPSLIMIT_SENSITIVE,
            memlimit=argon2id.MEMLIMIT_SENSITIVE
        )
        
        # Store: salt (16 bytes) + hash (32 bytes)
        return base64.b64encode(salt + hash_bytes).decode()

    def verify_pin(self, pin: str, stored_hash: str) -> bool:
        """Verify PIN against stored hash"""
        try:
            data = base64.b64decode(stored_hash)
            salt = data[:16]
            stored_key = data[16:48]

            computed_key = argon2id.kdf(
                size=32,
                password=pin.encode(),
                salt=salt,
                opslimit=argon2id.OPSLIMIT_SENSITIVE,
                memlimit=argon2id.MEMLIMIT_SENSITIVE
            )

            return secrets.compare_digest(computed_key, stored_key)

        except Exception as e:
            logger.error("PIN verification failed", error=str(e))
            return False

    def encrypt_sensitive_data(self, data: str) -> str:
        """Encrypt any sensitive data"""
        return self.encrypt_private_key(data)

    def decrypt_sensitive_data(self, encrypted_data: str) -> str:
        """Decrypt any sensitive data"""
        return self.decrypt_private_key(encrypted_data)

    @staticmethod
    def generate_secure_token(length: int = 32) -> str:
        """Generate cryptographically secure token"""
        return secrets.token_urlsafe(length)

    @staticmethod
    def generate_referral_code() -> str:
        """Generate unique referral code"""
        return secrets.token_urlsafe(6).upper()[:8]

    @staticmethod
    def generate_random_bytes(length: int = 32) -> bytes:
        """Generate random bytes"""
        return secrets.token_bytes(length)


# Global encryption manager instance
encryption_manager = EncryptionManager()