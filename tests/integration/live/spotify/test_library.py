import json
from collections.abc import AsyncGenerator

import pytest

from museflow import __project_name__
from museflow.domain.entities.music import Track
from museflow.domain.entities.user import User
from museflow.domain.mappers.auth import auth_token_create_from_token_payload
from museflow.domain.ports.repositories.auth import OAuthProviderTokenRepository
from museflow.domain.types import MusicProvider
from museflow.infrastructure.adapters.providers.spotify.client import SpotifyOAuthClientAdapter
from museflow.infrastructure.adapters.providers.spotify.library import SpotifyLibraryAdapter
from museflow.infrastructure.adapters.providers.spotify.mappers import to_domain_track
from museflow.infrastructure.adapters.providers.spotify.schemas import SpotifyPage
from museflow.infrastructure.adapters.providers.spotify.schemas import SpotifyTrack
from museflow.infrastructure.adapters.providers.spotify.session import SpotifyOAuthSessionClient
from museflow.infrastructure.entrypoints.cli.dependencies import get_spotify_client

from tests import ASSETS_DIR


@pytest.mark.spotify_live
class TestSpotifyLibraryLive:
    """
    Live integration tests against the real Spotify API.

    These tests verify that the Spotify API contract hasn't changed and that our
    Client Adapter correctly handles real-world responses.

    Requirements:
        - A valid `SPOTIFY_REFRESH_TOKEN` provided via CLI flag or env var.
        - Real `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` configured.
        - Network access to api.spotify.com.

    Warning:
        These tests are slow and depend on external services. They are NOT run by default.

    To run them manually:
    * run the database
    * connect a user account with Spotify and manually copy its real refresh token from the DB

    Then execute:
    > SPOTIFY_CLIENT_ID=<REAL_CLIENT_ID> SPOTIFY_CLIENT_SECRET=<REAL_CLIENT_SECRET> uv run pytest ./tests/integration/live --spotify-refresh-token=<REFRESH_TOKEN>
    """

    @pytest.fixture
    def spotify_refresh_token(self, request: pytest.FixtureRequest) -> str:
        token = request.config.getoption("--spotify-refresh-token")
        if not token:
            pytest.skip("Skipping live Spotify tests (missing token)")
        return token

    @pytest.fixture
    async def spotify_client_live(self) -> AsyncGenerator[SpotifyOAuthClientAdapter]:
        async with get_spotify_client() as client:
            yield client

    @pytest.fixture
    async def spotify_session_live(
        self,
        user: User,
        auth_token_repository: OAuthProviderTokenRepository,
        spotify_refresh_token: str,
        spotify_client_live: SpotifyOAuthClientAdapter,
    ) -> SpotifyOAuthSessionClient:
        token_payload = await spotify_client_live.refresh_access_token(spotify_refresh_token)

        auth_token = await auth_token_repository.create(
            user_id=user.id,
            provider=MusicProvider.SPOTIFY,
            auth_token_data=auth_token_create_from_token_payload(token_payload),
        )

        return SpotifyOAuthSessionClient(
            user=user,
            auth_token=auth_token,
            auth_token_repository=auth_token_repository,
            client=spotify_client_live,
        )

    @pytest.fixture
    def spotify_library_live(
        self, user: User, spotify_session_live: SpotifyOAuthSessionClient
    ) -> SpotifyLibraryAdapter:
        return SpotifyLibraryAdapter(user=user, session_client=spotify_session_live)

    @pytest.fixture
    def tracks(self, user: User) -> list[Track]:
        filepath = ASSETS_DIR / "wiremock" / "spotify" / "__files" / "top_tracks_page_1.json"
        top_tracks_response = json.loads(filepath.read_text())
        top_track_page = SpotifyPage[SpotifyTrack].model_validate(top_tracks_response)

        return [
            to_domain_track(SpotifyTrack.model_validate(item), user_id=user.id) for item in top_track_page.items[:3]
        ]

    async def test_top_artists(self, spotify_library_live: SpotifyLibraryAdapter) -> None:
        top_artists = await spotify_library_live.get_top_artists(page_size=5, max_pages=1)
        assert len(top_artists) == 5

    async def test_top_tracks(self, spotify_library_live: SpotifyLibraryAdapter) -> None:
        top_tracks = await spotify_library_live.get_top_tracks(page_size=5, max_pages=1)
        assert len(top_tracks) == 5

    async def test_saved_tracks(self, spotify_library_live: SpotifyLibraryAdapter) -> None:
        saved_tracks = await spotify_library_live.get_saved_tracks(page_size=5, max_pages=1)
        assert len(saved_tracks) == 5

    async def test_playlist_tracks(self, spotify_library_live: SpotifyLibraryAdapter) -> None:
        playlist_tracks = await spotify_library_live.get_playlist_tracks(page_size=2, max_pages=1)
        assert len(playlist_tracks) == 2 * (2 * 1)

    async def test_search(self, spotify_library: SpotifyLibraryAdapter) -> None:
        tracks = await spotify_library.search_tracks(track="bedstories", page_size=5, max_pages=1)
        assert len(tracks) == 5

    async def test_playlist_create(
        self,
        spotify_library_live: SpotifyLibraryAdapter,
        tracks: list[Track],
    ) -> None:
        playlist = await spotify_library_live.create_playlist(
            name=f"[{__project_name__}] - LIVE INTEGRATION TEST",
            tracks=tracks,
        )
        assert playlist.id is not None
        assert playlist.provider == MusicProvider.SPOTIFY
        assert playlist.provider_id is not None
