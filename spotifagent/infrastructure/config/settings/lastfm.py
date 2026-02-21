from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict

from spotifagent import BASE_DIR


class LastFMSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LASTFM_",
        env_file=[BASE_DIR / ".env"],
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    CLIENT_API_KEY: str
    CLIENT_SECRET: str

    HTTP_TIMEOUT: float = 30.0


lastfm_settings = LastFMSettings()
