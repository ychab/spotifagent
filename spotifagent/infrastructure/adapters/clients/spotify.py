import asyncio
import base64
from typing import Any
from typing import ClassVar
from typing import Final
from urllib.parse import urlencode

import httpx
from httpx import codes

from pydantic import HttpUrl

from tenacity import TryAgain
from tenacity import retry
from tenacity import retry_if_exception
from tenacity import stop_after_attempt
from tenacity import wait_exponential

from spotifagent.domain.entities.spotify import SpotifyScope
from spotifagent.domain.entities.spotify import SpotifyTokenState
from spotifagent.domain.ports.clients.spotify import SpotifyClientPort


def _is_retryable_error(exception: BaseException) -> bool:
    if isinstance(exception, httpx.RequestError):  # Retry network error
        return True

    if isinstance(exception, httpx.HTTPStatusError):  # Retry 429 and 5xx only
        return exception.response.status_code == codes.TOO_MANY_REQUESTS or exception.response.status_code >= 500

    if isinstance(exception, TryAgain):  # Manual retry signal (used for 429 with header)
        return True  # pragma: no cover (Tenacity may handle this internally, but required for safety)

    return False


class SpotifyClientAdapter(SpotifyClientPort):
    """Async Spotify user API client with OAuth and automatic token refresh."""

    BASE_URL: Final[ClassVar[HttpUrl]] = HttpUrl("https://api.spotify.com/v1")
    AUTH_ENDPOINT: Final[ClassVar[HttpUrl]] = HttpUrl("https://accounts.spotify.com/authorize")
    TOKEN_ENDPOINT: Final[ClassVar[HttpUrl]] = HttpUrl("https://accounts.spotify.com/api/token")

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: HttpUrl,
        timeout: float = 30.0,
        token_buffer_seconds: int = 300,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.token_buffer_seconds = token_buffer_seconds

        self._client: httpx.AsyncClient = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
        )

    def _get_basic_auth_header(self) -> str:
        credentials = f"{self.client_id}:{self.client_secret}"
        encoded = base64.b64encode(credentials.encode()).decode()
        return f"Basic {encoded}"

    @property
    def token_endpoint(self) -> HttpUrl:
        return self.TOKEN_ENDPOINT

    def get_authorization_url(self, scopes: list[SpotifyScope], state: str) -> tuple[HttpUrl, str]:
        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": str(self.redirect_uri),
            "scope": SpotifyScope.to_scope_string(scopes),
            "state": state,
        }

        return HttpUrl(f"{self.AUTH_ENDPOINT}?{urlencode(params)}"), state

    async def exchange_code_for_token(self, code: str) -> SpotifyTokenState:
        response = await self._client.post(
            str(self.token_endpoint),
            headers={
                "Authorization": self._get_basic_auth_header(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": str(self.redirect_uri),
            },
        )
        response.raise_for_status()

        return SpotifyTokenState.model_validate(response.json())

    async def refresh_access_token(self, refresh_token: str) -> SpotifyTokenState:
        response = await self._client.post(
            str(self.token_endpoint),
            headers={
                "Authorization": self._get_basic_auth_header(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )
        response.raise_for_status()

        token_data = response.json()
        # Spotify doesn't always return a new refresh token
        if "refresh_token" not in token_data:
            token_data["refresh_token"] = refresh_token

        return SpotifyTokenState.model_validate(token_data)

    @retry(
        retry=retry_if_exception(_is_retryable_error),
        wait=wait_exponential(multiplier=1, min=2, max=60),  # 2 + 4 + 8 + 16 + 32 = 62 seconds
        stop=stop_after_attempt(5),
        reraise=True,
    )
    async def make_user_api_call(
        self,
        method: str,
        endpoint: str,
        token_state: SpotifyTokenState,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
        enforce_refresh_token: bool = False,
    ) -> tuple[dict[str, Any], SpotifyTokenState]:
        # Check if token needs refresh
        if token_state.is_expired(self.token_buffer_seconds) or enforce_refresh_token:
            token_state = await self.refresh_access_token(token_state.refresh_token)

        # Make the API call
        try:
            response = await self._client.request(
                method=method.upper(),
                url=f"{self.BASE_URL}{endpoint}",
                headers={
                    "Authorization": f"{token_state.token_type} {token_state.access_token}",
                    "Content-Type": "application/json",
                },
                params=params,
                json=json_data,
            )
            response.raise_for_status()

        except httpx.HTTPStatusError as e:
            # Token might be invalid in between, so try just one refresh.
            if e.response.status_code == codes.UNAUTHORIZED and not enforce_refresh_token:
                return await self.make_user_api_call(
                    method=method,
                    endpoint=endpoint,
                    token_state=token_state,
                    params=params,
                    json_data=json_data,
                    enforce_refresh_token=True,
                )

            # Special handling for 429 with Retry-After header returned by Spotify
            if e.response.status_code == codes.TOO_MANY_REQUESTS:
                retry_after = e.response.headers.get("Retry-After")
                if retry_after:
                    wait_seconds = int(retry_after) + 1
                    await asyncio.sleep(wait_seconds)
                    # Because we slept as Spotify asked us, we must raise a
                    # TryAgain to prevent Tenacity to sleep again for nothing.
                    raise TryAgain() from e

            raise

        if response.status_code == codes.NO_CONTENT:
            return {}, token_state

        return response.json(), token_state

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "SpotifyClientAdapter":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()
