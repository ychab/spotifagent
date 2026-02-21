from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, Field

from spotifagent.domain.entities.base import BaseEntity


def _ensure_list(v: Any) -> list[Any]:
    """
    Last.fm sometimes returns a single object instead of a list
    when there is only one result. This validator ensures we always get a list.
    """
    if v is None:
        return []
    if not isinstance(v, list):
        return [v]
    return v


class LastFmArtist(BaseModel):
    name: str
    mbid: str | None = None


class LastFmTrack(BaseModel):
    name: str
    mbid: str | None = None
    match: float
    artist: LastFmArtist


class LastFmSimilarTracks(BaseModel):
    track: Annotated[list[LastFmTrack], BeforeValidator(_ensure_list)] = Field(default_factory=list)


class LastFmSimilarTracksResponse(BaseEntity):
    similartracks: LastFmSimilarTracks
