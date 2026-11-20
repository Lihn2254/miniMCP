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

    DEVICE_NAME: str = f"Soloist-{platform.node()}" or "SOLOIST-DEVICE"

    SERVER_TRANSPORT: str = "http"
    SERVER_HOST: str = "127.0.0.1"
    SERVER_PORT: int = 8000
    SERVER_PATH: str = "/mcp"

    SOLOIST_API_KEY: str

    @field_validator("MUSIC_FILE", "SOLOIST_LOG")
    @classmethod
    def _resolve_relative_to_server_dir(cls, value: Path) -> Path:
        """Relative paths (e.g. `MUSIC_FILE=albums.json` in .env) are resolved
        against the server directory, not the current working directory."""
        return value if value.is_absolute() else (SERVER_DIR / value).resolve()

    @field_validator("SERVER_TRANSPORT")
    @classmethod
    def _validate_server_transport(cls, server_transport: str) -> str:
        if server_transport not in ["http", "stdio"]:
            raise Exception('SERVER_TRANSPORT must be "http" or "stdio"')
        return server_transport

    @field_validator("SERVER_PATH")
    @classmethod
    def _normalize_server_path(cls, server_path: str) -> str:
        """Ensure a single leading slash and no trailing slash (e.g. `mcp/` -> `/mcp`)."""
        server_path = "/" + server_path.strip().strip("/")
        if server_path == "/":
            raise ValueError("SERVER_PATH must not be empty or '/'")
        return server_path

    @field_validator("SOLOIST_API_KEY")
    @classmethod
    def _validate_soloist_api_key(cls, soloist_api_key: str) -> str:
        if not soloist_api_key:
            raise Exception("SOLOIST_API_KEY is missing")
        return soloist_api_key


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]