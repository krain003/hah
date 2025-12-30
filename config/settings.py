from pydantic_settings import BaseSettings
from pydantic import Field, SecretStr
from typing import List

class Settings(BaseSettings):
    # Telegram Bot Token from @BotFather
    BOT_TOKEN: SecretStr = Field(..., alias="TG_BOT_TOKEN")
    
    # URL of your deployed Web App (from Render)
    WEB_APP_URL: str = Field("https://example.onrender.com", alias="WEB_APP_URL")

    # Security Keys (generate random long strings)
    SECURITY_MASTER_KEY: SecretStr = Field(..., alias="SECURITY_MASTER_KEY")
    SECURITY_ENCRYPTION_SALT: SecretStr = Field(..., alias="SECURITY_ENCRYPTION_SALT")
    
    # Optional: Admin IDs for notifications
    ADMIN_IDS: List[int] = Field([], alias="TG_ADMIN_IDS")

    class Config:
        # This tells pydantic to read from a .env file
        env_file = ".env"
        # This makes it ignore case sensitivity for env variables
        case_sensitive = False

# --- САМАЯ ВАЖНАЯ СТРОКА, КОТОРОЙ НЕ ХВАТАЛО ---
# Создаем глобальный экземпляр настроек, который импортируется в других файлах
settings = Settings()