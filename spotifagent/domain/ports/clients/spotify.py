from abc import ABC
from abc import abstractmethod
from typing import Any

from pydantic import HttpUrl

from spotifagent.domain.entities.spotify import SpotifyScope
from spotifagent.domain.entities.spotify import SpotifyTokenState


class SpotifyClientPort(ABC):
    """Port interface for Spotify user API client."""

    @property
    @abstractmethod
    def token_endpoint(self) -> HttpUrl: ...

    @abstractmethod
    def get_authorization_url(self, scopes: list[SpotifyScope], state: str) -> tuple[HttpUrl, str]:
        """Generate OAuth authorization URL."""
        ...

    @abstractmethod
    async def exchange_code_for_token(self, code: str) -> SpotifyTokenState:
        """Exchange authorization code for access token."""
        ...

    @abstractmethod
    async def refresh_access_token(self, refresh_token: str) -> SpotifyTokenState:
        """Refresh an expired access token."""
        ...

    @abstractmethod
    async def make_user_api_call(
        self,
        method: str,
        endpoint: str,
        token_state: SpotifyTokenState,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], SpotifyTokenState]:
        """
        Make an authenticated user API call with automatic token refresh.

        This method automatically refreshes the access token if it's expired or about to expire.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE, etc.)
            endpoint: User API endpoint path (must start with /me or /users/{user_id})
            token_state: Current user token state
            params: Query parameters
            json_data: JSON body for POST/PUT requests

        Returns:
            Tuple of (response_data, SpotifyTokenState)
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """Close the client and cleanup resources."""
        ...
