"""
NEXUS WALLET - Configuration Settings
"""

from pydantic_settings import BaseSettings
from pydantic import Field, SecretStr
from typing import Optional, List
from functools import lru_cache


class SecuritySettings:
    """Security settings"""
    MASTER_KEY: SecretStr = SecretStr("change-me-32-bytes-key-here!!")
    ENCRYPTION_SALT: SecretStr = SecretStr("change-me-salt-16bytes")


class Settings(BaseSettings):
    # Environment
    ENV: str = Field(default="development")
    DEBUG: bool = Field(default=False)

    # Telegram
    BOT_TOKEN: SecretStr = Field(alias="TG_BOT_TOKEN")
    BOT_USERNAME: str = Field(default="NexusWalletBot", alias="TG_BOT_USERNAME")
    ADMIN_IDS: List[int] = Field(default=[], alias="TG_ADMIN_IDS")
    SUPER_ADMIN_IDS: List[int] = Field(default=[], alias="TG_SUPER_ADMIN_IDS")

    # Database
    POSTGRES_HOST: str = Field(default="localhost", alias="DB_POSTGRES_HOST")
    POSTGRES_PORT: int = Field(default=5432, alias="DB_POSTGRES_PORT")
    POSTGRES_USER: str = Field(default="nexus", alias="DB_POSTGRES_USER")
    POSTGRES_PASSWORD: SecretStr = Field(default="password", alias="DB_POSTGRES_PASSWORD")
    POSTGRES_DB: str = Field(default="nexus_wallet", alias="DB_POSTGRES_DB")

    REDIS_HOST: str = Field(default="localhost", alias="DB_REDIS_HOST")
    REDIS_PORT: int = Field(default=6379, alias="DB_REDIS_PORT")

    # Security settings as property
    @property
    def security(self) -> SecuritySettings:
        return SecuritySettings()

    # Blockchain
    ETH_RPC_URL: str = Field(default="https://eth.llamarpc.com", alias="BLOCKCHAIN_ETH_RPC_URL")
    BSC_RPC_URL: str = Field(default="https://bsc-dataseed1.binance.org", alias="BLOCKCHAIN_BSC_RPC_URL")
    POLYGON_RPC_URL: str = Field(default="https://polygon-rpc.com", alias="BLOCKCHAIN_POLYGON_RPC_URL")
    SOLANA_RPC_URL: str = Field(default="https://api.mainnet-beta.solana.com", alias="BLOCKCHAIN_SOLANA_RPC_URL")

    @property
    def postgres_url(self) -> str:
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD.get_secret_value()}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    @property
    def redis_url(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/0"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()