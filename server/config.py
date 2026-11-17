from functools import lru_cache
import os, platform
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    MUSIC_FILE: Path = Path(__file__).resolve().parent / os.environ.get(
        key="MUSIC_FILE", default="albums.json"
    )

    SOLOIST_LOG: Path = Path(__file__).resolve().parent / "soloist.log"

    DEVICE_NAME: str = platform.node() or "SOLOIST_DEVICE"

@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]