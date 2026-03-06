from collections.abc import Sequence
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from typing import Annotated
from typing import Any

from pydantic import AwareDatetime
from pydantic import BaseModel
from pydantic import Field
from pydantic import HttpUrl
from pydantic import NonNegativeInt
from pydantic import computed_field
from pydantic import model_validator

from pydantic_core import PydanticCustomError

from museflow.infrastructure.adapters.providers.spotify.types import LocalUnsupported


class SpotifyToken(BaseModel):
    token_type: str
    access_token: str
    refresh_token: str | None = None  # Sometimes refresh token isn't returned on refresh
    expires_in: NonNegativeInt

    @computed_field
    def expires_at(self) -> datetime:
        return datetime.now(UTC) + timedelta(seconds=self.expires_in)


class SpotifyTrackArtist(BaseModel):
    id: str
    name: str


class SpotifyItem(BaseModel):
    id: str = Field(..., max_length=512)
    name: str = Field(..., max_length=255)
    href: HttpUrl


class SpotifyPlaylist(SpotifyItem):
    snapshot_id: str
    public: bool
    collaborative: bool


class SpotifyArtist(SpotifyItem):
    popularity: int = Field(..., ge=0, le=100)
    genres: list[str]


class SpotifyTrack(SpotifyItem):
    popularity: int = Field(..., ge=0, le=100)
    is_local: bool
    artists: list[SpotifyTrackArtist]

    @model_validator(mode="before")
    @classmethod
    def check_is_local(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("is_local") is True:
            raise PydanticCustomError(
                LocalUnsupported,
                "Unsupported local file",
            )
        return data


class SpotifySavedTrack(BaseModel):
    added_at: AwareDatetime | None = None
    track: SpotifyTrack


class SpotifyPlaylistTrack(BaseModel):
    item: SpotifyTrack


class SpotifyPage[T: SpotifyItem | SpotifySavedTrack | SpotifyPlaylistTrack](BaseModel):
    """Generic Pydantic model for paginated Spotify API responses.

    This model is used to parse responses that contain a list of items,
    along with pagination metadata such as total count, limit, and offset.
    """

    items: Sequence[T]
    total: Annotated[int, Field(ge=0)]
    limit: Annotated[int, Field(ge=0)]
    offset: Annotated[int, Field(ge=0)]
