from abc import ABC
from abc import abstractmethod
from typing import Any

from pydantic import HttpUrl

from spotifagent.domain.entities.lastfm import LastFmTrack


class LastFmClientPort(ABC):
    """Port interface for Last.fm API client."""

    @property
    @abstractmethod
    def base_url(self) -> HttpUrl: ...

    @abstractmethod
    async def get_similar_tracks(self, artist_name: str, track_name: str, limit: int = 5) -> list[LastFmTrack]: ...

    @abstractmethod
    async def make_api_call(
        self,
        method: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        ...

    @abstractmethod
    async def close(self) -> None: ...
