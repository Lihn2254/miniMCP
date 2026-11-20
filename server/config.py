from functools import lru_cache
import platform
from pathlib import Path
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


SERVER_DIR = Path(__file__).resolve().parent
ENV_FILE = SERVER_DIR.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Absolute path so the .env is found regardless of the working directory.
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    MUSIC_FILE: Path = SERVER_DIR / "albums.json"

    SOLOIST_LOG: Path = SERVER_DIR / "soloist.log"

    DEVICE_NAME: str = f"Soloist-{platform.node()}" or "SOLOIST_DEVICE"

    @field_validator("MUSIC_FILE", "SOLOIST_LOG")
    @classmethod
    def _resolve_relative_to_server_dir(cls, value: Path) -> Path:
        """Relative paths (e.g. `MUSIC_FILE=albums.json` in .env) are resolved
        against the server directory, not the current working directory."""
        return value if value.is_absolute() else (SERVER_DIR / value).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]