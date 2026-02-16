import uuid
from collections.abc import Sequence
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from enum import StrEnum
from typing import Annotated
from typing import Any
from typing import Self

from pydantic import AwareDatetime
from pydantic import BaseModel
from pydantic import Field
from pydantic import HttpUrl
from pydantic import model_validator

from spotifagent.domain.entities.base import BaseEntity


class SpotifyScope(StrEnum):
    """Spotify OAuth scopes for user-related operations.

    See: https://developer.spotify.com/documentation/web-api/concepts/scopes
    """

    # Listening History
    USER_READ_PLAYBACK_STATE = "user-read-playback-state"
    USER_MODIFY_PLAYBACK_STATE = "user-modify-playback-state"
    USER_READ_CURRENTLY_PLAYING = "user-read-currently-playing"

    # Spotify Connect
    STREAMING = "streaming"

    # Playlists
    PLAYLIST_READ_PRIVATE = "playlist-read-private"
    PLAYLIST_READ_COLLABORATIVE = "playlist-read-collaborative"
    PLAYLIST_MODIFY_PRIVATE = "playlist-modify-private"
    PLAYLIST_MODIFY_PUBLIC = "playlist-modify-public"

    # Follow
    USER_FOLLOW_MODIFY = "user-follow-modify"
    USER_FOLLOW_READ = "user-follow-read"

    # Playback
    USER_READ_PLAYBACK_POSITION = "user-read-playback-position"
    USER_TOP_READ = "user-top-read"
    USER_READ_RECENTLY_PLAYED = "user-read-recently-played"

    # Library
    USER_LIBRARY_MODIFY = "user-library-modify"
    USER_LIBRARY_READ = "user-library-read"

    # Users
    USER_READ_EMAIL = "user-read-email"
    USER_READ_PRIVATE = "user-read-private"

    @classmethod
    def all(cls) -> list[Self]:
        return list(cls)

    @classmethod
    def required_scopes(cls) -> list[Self]:
        return [
            cls.USER_TOP_READ,
            cls.USER_LIBRARY_READ,
            cls.PLAYLIST_READ_PRIVATE,
        ]

    @classmethod
    def to_scope_string(cls, scopes: list[Self]) -> str:
        return " ".join(scope.value for scope in scopes)


class SpotifyTokenState(BaseModel):
    """User token state with expiration tracking."""

    token_type: str
    access_token: str
    refresh_token: str
    expires_at: AwareDatetime

    def is_expired(self, buffer_seconds: int = 60) -> bool:
        return datetime.now(UTC) >= self.expires_at - timedelta(seconds=buffer_seconds)

    @model_validator(mode="before")
    @classmethod
    def calculate_expires_at(cls, data: Any) -> Any:
        # Special handling for input data coming from Spotify API.
        if isinstance(data, dict) and not data.get("expires_at"):
            if "expires_in" in data and isinstance(data["expires_in"], int) and data["expires_in"] > 0:
                data["expires_at"] = datetime.now(UTC) + timedelta(seconds=data["expires_in"])
            else:
                raise ValueError("Input must contain a positive integer 'expires_in' or 'expires_at")

        return data

    def to_user_create(self) -> "SpotifyAccountCreate":
        return SpotifyAccountCreate(
            token_type=self.token_type,
            token_access=self.access_token,
            token_refresh=self.refresh_token,
            token_expires_at=self.expires_at,
        )

    def to_user_update(self) -> "SpotifyAccountUpdate":
        return SpotifyAccountUpdate(
            token_type=self.token_type,
            token_access=self.access_token,
            token_refresh=self.refresh_token,
            token_expires_at=self.expires_at,
        )


class BaseSpotifyAccount(BaseEntity):
    token_type: str = Field(..., max_length=512)
    token_access: str = Field(..., max_length=512)
    token_refresh: str = Field(..., max_length=512)
    token_expires_at: AwareDatetime


class SpotifyAccount(BaseSpotifyAccount):
    id: int
    user_id: uuid.UUID


class SpotifyAccountCreate(BaseSpotifyAccount):
    pass


class SpotifyAccountUpdate(BaseEntity):
    token_type: str | None = Field(None, max_length=512)
    token_access: str | None = Field(None, max_length=512)
    token_refresh: str | None = Field(None, max_length=512)
    token_expires_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_one_field_set(self):
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided for update")
        return self


class SpotifyTrackArtist(BaseModel):
    id: str
    name: str


class SpotifyItem(BaseModel):
    id: str
    name: str
    href: HttpUrl


class SpotifyPlaylist(SpotifyItem):
    pass


class SpotifyArtist(SpotifyItem):
    popularity: int
    genres: list[str]


class SpotifyTrack(SpotifyItem):
    popularity: int
    artists: list[SpotifyTrackArtist]


class SpotifySavedTrack(BaseModel):
    added_at: AwareDatetime | None = None
    track: SpotifyTrack


class SpotifyPlaylistTrack(BaseModel):
    item: SpotifyTrack


class SpotifyPage[T: SpotifyItem | SpotifySavedTrack | SpotifyPlaylistTrack](BaseModel):
    items: Sequence[T]
    total: Annotated[int, Field(ge=0)]
    limit: Annotated[int, Field(ge=1)]
    offset: Annotated[int, Field(ge=0)]


class SpotifyPlaylistPage(SpotifyPage[SpotifyPlaylist]): ...


class SpotifySavedTrackPage(SpotifyPage[SpotifySavedTrack]): ...


class SpotifyPlaylistTrackPage(SpotifyPage[SpotifyPlaylistTrack]): ...


class SpotifyTopArtistPage(SpotifyPage[SpotifyArtist]): ...


class SpotifyTopTrackPage(SpotifyPage[SpotifyTrack]): ...
