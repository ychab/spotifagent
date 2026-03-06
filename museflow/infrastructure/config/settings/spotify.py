from pydantic import Field
from pydantic import HttpUrl
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict

from museflow import BASE_DIR


class SpotifySettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SPOTIFY_",
        env_file=[BASE_DIR / ".env"],
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    CLIENT_ID: str
    CLIENT_SECRET: str

    BASE_URL: HttpUrl = Field(default=HttpUrl("https://api.spotify.com/v1"))
    AUTH_ENDPOINT: HttpUrl = Field(default=HttpUrl("https://accounts.spotify.com/authorize"))
    TOKEN_ENDPOINT: HttpUrl = Field(default=HttpUrl("https://accounts.spotify.com/api/token"))

    REDIRECT_URI: HttpUrl = Field(default=HttpUrl("http://127.0.0.1:8000/api/v1/spotify/callback"))

    HTTP_TIMEOUT: float = 30.0
    HTTP_MAX_RETRIES: int = 5

    TOKEN_BUFFER_SECONDS: int = 60 * 5


spotify_settings = SpotifySettings()
