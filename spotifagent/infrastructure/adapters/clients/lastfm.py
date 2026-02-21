from typing import Any, Final, ClassVar

import httpx
from httpx import codes
from pydantic import HttpUrl
from tenacity import stop_after_attempt, wait_exponential, retry_if_exception, retry

from spotifagent.domain.entities.lastfm import LastFmSimilarTracksResponse, LastFmTrack
from spotifagent.domain.ports.clients.lastfm import LastFmClientPort


def _is_retryable_error(exception: BaseException) -> bool:
    if isinstance(exception, httpx.RequestError):  # Retry network error
        return True

    if isinstance(exception, httpx.HTTPStatusError):  # Retry 429 and 5xx only
        return exception.response.status_code == codes.TOO_MANY_REQUESTS or exception.response.status_code >= 500

    return False


class LastFmClientAdapter(LastFmClientPort):

    BASE_URL: Final[ClassVar[HttpUrl]] = HttpUrl("http://ws.audioscrobbler.com/2.0/")

    def __init__(
        self,
        client_api_key: str,
        client_secret: str,
        timeout: float = 30.0,
    ) -> None:
        self.client_api_key = client_api_key
        self.client_secret = client_secret

        self._client: httpx.AsyncClient = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
        )

    @property
    def base_url(self) -> HttpUrl:
        return self.BASE_URL

    async def get_similar_tracks(self, artist_name: str, track_name: str, limit: int = 5) -> list[LastFmTrack]:
        response_data = await self.make_api_call(
            method="GET",
            params={
                "method": "track.getSimilar",
                "artist": artist_name,
                "track": track_name,
                "limit": limit,
                "autocorrect": 1,
            },
        )
        tracks = LastFmSimilarTracksResponse.model_validate(response_data).similartracks.track
        return sorted(tracks, key=lambda t: t.match, reverse=True)


    @retry(
        retry=retry_if_exception(_is_retryable_error),
        wait=wait_exponential(multiplier=1, min=2, max=60),  # 2 + 4 + 8 + 16 + 32 = 62 seconds
        stop=stop_after_attempt(5),
        reraise=True,
    )
    async def make_api_call(
        self,
        method: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:

        response = await self._client.request(
            method=method.upper(),
            url=f"{self.BASE_URL}",
            params={
                "api_key": self.client_api_key,
                "format": "json",
                **params,
            },
        )
        response.raise_for_status()

        if response.status_code == codes.NO_CONTENT:
            return {}

        return response.json()

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "LastFmClientAdapter":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

