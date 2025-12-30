from pydantic_settings import BaseSettings
from pydantic import Field, SecretStr
from typing import List

class Settings(BaseSettings):
    BOT_TOKEN: SecretStr = Field(alias="TG_BOT_TOKEN")
    WEB_APP_URL: str = Field("https://default.com", alias="WEB_APP_URL")
    # ... и другие настройки
    class Config:
        env_file = ".env"