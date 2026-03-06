import asyncio
import base64
import logging
from typing import Any
from urllib.parse import urlencode

import httpx
from httpx import codes

from pydantic import HttpUrl

from tenacity import TryAgain
from tenacity import retry
from tenacity import retry_if_exception
from tenacity import stop_after_attempt
from tenacity import wait_exponential

from museflow.domain.ports.providers.client import ProviderOAuthClientPort
from museflow.domain.schemas.auth import OAuthProviderTokenPayload
from museflow.infrastructure.adapters.providers.spotify.exceptions import SpotifyTokenExpiredError
from museflow.infrastructure.adapters.providers.spotify.mappers import to_domain_token_payload
from museflow.infrastructure.adapters.providers.spotify.schemas import SpotifyToken
from museflow.infrastructure.adapters.providers.spotify.types import SpotifyScope
from museflow.infrastructure.config.settings.spotify import spotify_settings

logger = logging.getLogger(__name__)


def _is_retryable_error(exception: BaseException) -> bool:
    if isinstance(exception, SpotifyTokenExpiredError):
        return False  # Let the Session handler deal with this!

    if isinstance(exception, httpx.HTTPStatusError):  # Retry 429 and 5xx only
        return exception.response.status_code == codes.TOO_MANY_REQUESTS or exception.response.status_code >= 500

    # Retry network error OR manual retry signal (used for 429 with header)
    if isinstance(exception, (httpx.RequestError, TryAgain)):
        return True  # Tenacity may handle the TryAgain internally, but we keep it here for safety

    return False


class SpotifyOAuthClientAdapter(ProviderOAuthClientPort):
    """An asynchronous Spotify API client with OAuth and automatic token refresh.

    This adapter includes robust retry logic for handling transient network errors and
    rate limiting (429 Too Many Requests).
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: HttpUrl,
        base_url: HttpUrl | None = None,
        auth_endpoint: HttpUrl | None = None,
        token_endpoint: HttpUrl | None = None,
        verify_ssl: bool = True,
        timeout: float = 30.0,
        token_buffer_seconds: int = 300,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

        self._base_url = base_url or HttpUrl("https://api.spotify.com/v1")
        self._auth_endpoint = auth_endpoint or HttpUrl("https://accounts.spotify.com/authorize")
        self._token_endpoint = token_endpoint or HttpUrl("https://accounts.spotify.com/api/token")

        self.token_buffer_seconds = token_buffer_seconds

        self._client: httpx.AsyncClient = httpx.AsyncClient(
            verify=verify_ssl,
            timeout=timeout,
            follow_redirects=True,
        )

    def _get_basic_auth_header(self) -> str:
        credentials = f"{self.client_id}:{self.client_secret}"
        encoded = base64.b64encode(credentials.encode()).decode()
        return f"Basic {encoded}"

    @property
    def base_url(self) -> HttpUrl:
        return self._base_url

    @property
    def token_endpoint(self) -> HttpUrl:
        return self._token_endpoint

    def get_authorization_url(self, state: str) -> HttpUrl:
        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": str(self.redirect_uri),
            "scope": SpotifyScope.required_scopes(),
            "state": state,
        }

        return HttpUrl(f"{self._auth_endpoint}?{urlencode(params)}")

    async def exchange_code_for_token(self, code: str) -> OAuthProviderTokenPayload:
        response = await self._client.post(
            url=str(self.token_endpoint),
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
        if response.is_error:
            logger.error(
                "Spotify Token Exchange Failed",
                extra={
                    "status_code": response.status_code,
                    "response_text": response.text,
                    "redirect_uri": str(self.redirect_uri),
                },
            )

        response.raise_for_status()

        return to_domain_token_payload(SpotifyToken(**response.json()))

    async def refresh_access_token(self, refresh_token: str) -> OAuthProviderTokenPayload:
        response = await self._client.post(
            url=str(self.token_endpoint),
            headers={
                "Authorization": self._get_basic_auth_header(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )
        if response.is_error:
            logger.error(
                "Spotify Token Refresh Failed",
                extra={"status_code": response.status_code, "response_text": response.text},
            )

        response.raise_for_status()

        return to_domain_token_payload(SpotifyToken(**response.json()), refresh_token)

    @retry(
        retry=retry_if_exception(_is_retryable_error),
        wait=wait_exponential(multiplier=1, min=2, max=60),  # 2 + 4 + 8 + 16 + 32 = 62 seconds
        stop=stop_after_attempt(spotify_settings.HTTP_MAX_RETRIES),
        reraise=True,
    )
    async def make_user_api_call(
        self,
        method: str,
        endpoint: str,
        token_payload: OAuthProviderTokenPayload,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Makes an authenticated API call to the Spotify API.

        This method includes retry logic for transient errors and rate limiting.
        It specifically handles the `Retry-After` header from Spotify for 429 responses.
        """
        try:
            response = await self._client.request(
                method=method.upper(),
                url=f"{str(self.base_url).rstrip('/')}{endpoint}",
                headers={
                    "Authorization": f"{token_payload.token_type} {token_payload.access_token}",
                    "Content-Type": "application/json",
                },
                params=params,
                json=json_data,
            )
            response.raise_for_status()

        except httpx.HTTPStatusError as e:
            # Explicitly check for 401 first to bypass retry logic
            if e.response.status_code == codes.UNAUTHORIZED:
                raise SpotifyTokenExpiredError() from e

            # Special handling for 429 with Retry-After header returned by Spotify
            if e.response.status_code == codes.TOO_MANY_REQUESTS:
                retry_after = e.response.headers.get("Retry-After")
                if retry_after:
                    wait_seconds = int(retry_after) + 1
                    await asyncio.sleep(wait_seconds)
                    # Because we slept as Spotify asked us, we must raise a
                    # TryAgain to prevent Tenacity to sleep again for nothing.
                    raise TryAgain() from e

            logger.exception(
                "Spotify API Error",
                extra={
                    "status_code": e.response.status_code,
                    "method": method,
                    "endpoint": endpoint,
                    "response_text": e.response.text,
                },
            )
            raise e

        if response.status_code == codes.NO_CONTENT:
            return {}

        return response.json()

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "SpotifyOAuthClientAdapter":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()
