import copy
import json
from typing import Any
from unittest import mock

import pytest

from spotifagent.application.services.spotify import SpotifySessionFactory
from spotifagent.application.services.spotify import SpotifyUserSession
from spotifagent.domain.entities.music import MusicProvider
from spotifagent.domain.entities.spotify import SpotifyAccountUpdate
from spotifagent.domain.entities.spotify import SpotifyTokenState
from spotifagent.domain.entities.users import User
from spotifagent.domain.exceptions import SpotifyAccountNotFoundError

from tests import ASSETS_DIR
from tests.unit.factories.spotify import SpotifyTokenStateFactory
from tests.unit.factories.users import UserFactory


class TestSpotifySessionFactory:
    @pytest.fixture
    def spotify_session_factory(
        self,
        mock_spotify_account_repository: mock.Mock,
        mock_spotify_client: mock.Mock,
    ) -> SpotifySessionFactory:
        return SpotifySessionFactory(
            spotify_account_repository=mock_spotify_account_repository,
            spotify_client=mock_spotify_client,
        )

    @pytest.mark.parametrize("user", [{"with_spotify_account": True}], indirect=True)
    def test_create__spotify_account__nominal(
        self,
        user: User,
        spotify_session_factory: SpotifySessionFactory,
    ) -> None:
        session = spotify_session_factory.create(user)
        assert isinstance(session, SpotifyUserSession)
        assert session.user == user

    @pytest.mark.parametrize("user", [{"with_spotify_account": False}], indirect=True)
    def test_create__spotify_account__not_found(
        self,
        user: User,
        spotify_session_factory: SpotifySessionFactory,
    ) -> None:
        with pytest.raises(SpotifyAccountNotFoundError):
            spotify_session_factory.create(user)


class TestSpotifyUserSession:
    @pytest.fixture
    def user(self) -> User:
        return UserFactory.build(with_spotify_account=True)

    @pytest.fixture
    def spotify_user_session(
        self,
        user: User,
        mock_spotify_account_repository: mock.AsyncMock,
        mock_spotify_client: mock.AsyncMock,
    ) -> SpotifyUserSession:
        return SpotifyUserSession(
            user=user,
            spotify_account_repository=mock_spotify_account_repository,
            spotify_client=mock_spotify_client,
        )

    @pytest.fixture
    def spotify_response(self, request: pytest.FixtureRequest) -> dict[str, Any]:
        filename: str = getattr(request, "param", "top_artists")
        filepath = ASSETS_DIR / "httpmock" / "spotify" / f"{filename}.json"
        return json.loads(filepath.read_text())

    @pytest.fixture(name="page_limit")
    def patch_spotify_response_paginated(
        self,
        spotify_response: dict[str, Any],
        token_state: SpotifyTokenState,
        mock_spotify_client: mock.AsyncMock,
    ) -> int:
        side_effects = []

        total: int = 20
        offset: int = 0
        limit: int = 5
        while offset + limit <= total:
            response_chunk = copy.deepcopy(spotify_response)
            response_chunk["offset"] = offset
            response_chunk["limit"] = limit
            response_chunk["total"] = total
            response_chunk["items"] = response_chunk["items"][offset : offset + limit]

            side_effects += [(response_chunk, token_state)]
            offset += limit

        mock_spotify_client.make_user_api_call.side_effect = side_effects
        return limit

    async def test__execute_request__persists_new_token(
        self,
        spotify_user_session: SpotifyUserSession,
        token_state: SpotifyTokenState,
        mock_spotify_client: mock.AsyncMock,
        mock_spotify_account_repository: mock.AsyncMock,
    ) -> None:
        mock_spotify_client.make_user_api_call.return_value = ({"data": "ok"}, token_state)

        await spotify_user_session._execute_request("GET", "/test")

        mock_spotify_account_repository.update.assert_called_once_with(
            user_id=spotify_user_session.user.id,
            spotify_account_data=SpotifyAccountUpdate(
                token_type=token_state.token_type,
                token_access=token_state.access_token,
                token_refresh=token_state.refresh_token,
                token_expires_at=token_state.expires_at,
            ),
        )

    async def test__execute_request__no_persistence_if_unchanged(
        self,
        spotify_user_session: SpotifyUserSession,
        user: User,
        mock_spotify_client: mock.AsyncMock,
        mock_spotify_account_repository: mock.AsyncMock,
    ) -> None:
        assert user.spotify_account is not None

        token_state_unchanged = SpotifyTokenStateFactory.build(access_token=user.spotify_account.token_access)
        mock_spotify_client.make_user_api_call.return_value = ({"data": "ok"}, token_state_unchanged)

        await spotify_user_session._execute_request("GET", "/test")

        mock_spotify_account_repository.update.assert_not_called()

    @pytest.mark.parametrize("spotify_response", ["top_artists"], indirect=["spotify_response"])
    async def test__get_top_artists__nominal(
        self,
        spotify_user_session: SpotifyUserSession,
        spotify_response: dict[str, Any],
        page_limit: int,
    ) -> None:
        top_artists = await spotify_user_session.get_top_artists(limit=page_limit)
        assert len(top_artists) == 20

        top_artist_first = top_artists[0]
        assert top_artist_first.id is not None
        assert top_artist_first.user_id == spotify_user_session.user.id
        assert top_artist_first.name == "Vald"
        assert top_artist_first.popularity == 68
        assert top_artist_first.is_saved is False
        assert top_artist_first.is_top is True
        assert top_artist_first.top_position == 1
        assert top_artist_first.genres == ["french rap"]
        assert top_artist_first.provider == MusicProvider.SPOTIFY
        assert top_artist_first.provider_id == "3CnCGFxXbOA8bAK54jR8js"

        top_artist_last = top_artists[-1]
        assert top_artist_last.id is not None
        assert top_artist_last.user_id == spotify_user_session.user.id
        assert top_artist_last.name == "Bad Bunny"
        assert top_artist_last.popularity == 99
        assert top_artist_last.is_saved is False
        assert top_artist_last.is_top is True
        assert top_artist_last.top_position == len(top_artists) == 20
        assert top_artist_last.genres == ["reggaeton", "trap latino", "urbano latino", "latin"]
        assert top_artist_last.provider == MusicProvider.SPOTIFY
        assert top_artist_last.provider_id == "4q3ewBCX7sLwd24euuV69X"

    @pytest.mark.parametrize("spotify_response", ["top_tracks"], indirect=["spotify_response"])
    async def test__get_top_tracks__nominal(
        self,
        spotify_user_session: SpotifyUserSession,
        spotify_response: dict[str, Any],
        page_limit: int,
    ) -> None:
        top_tracks = await spotify_user_session.get_top_tracks(limit=page_limit)
        assert len(top_tracks) == 20

        top_track_first = top_tracks[0]
        assert top_track_first.id is not None
        assert top_track_first.user_id == spotify_user_session.user.id
        assert top_track_first.name == "La Negra No Quiere"
        assert top_track_first.popularity == 20
        assert top_track_first.is_saved is False
        assert top_track_first.is_top is True
        assert top_track_first.top_position == 1
        assert len(top_track_first.artists) == 1
        assert top_track_first.artists[0].provider_id == "1zng9JZpblpk48IPceRWs8"
        assert top_track_first.artists[0].name == "Grupo Niche"
        assert top_track_first.provider == MusicProvider.SPOTIFY
        assert top_track_first.provider_id == "7J5pB49l9ycy9ImB6D9hu0"

        top_track_last = top_tracks[-1]
        assert top_track_last.id is not None
        assert top_track_last.user_id == spotify_user_session.user.id
        assert top_track_last.name == "Deux mille"
        assert top_track_last.popularity == 60
        assert top_track_last.is_saved is False
        assert top_track_last.is_top is True
        assert top_track_last.top_position == len(top_tracks) == 20
        assert len(top_track_last.artists) == 1
        assert top_track_last.artists[0].provider_id == "2kXKa3aAFngGz2P4GjG5w2"
        assert top_track_last.artists[0].name == "SCH"
        assert top_track_last.provider == MusicProvider.SPOTIFY
        assert top_track_last.provider_id == "03LDM6VoTJbfdw1L7USDU8"

    @pytest.mark.parametrize("spotify_response", ["saved_tracks"], indirect=["spotify_response"])
    async def test__get_saved_tracks__nominal(
        self,
        spotify_user_session: SpotifyUserSession,
        spotify_response: dict[str, Any],
        page_limit: int,
    ) -> None:
        tracks_saved = await spotify_user_session.get_saved_tracks(limit=page_limit)
        assert len(tracks_saved) == 20

        track_saved_first = tracks_saved[0]
        assert track_saved_first.id is not None
        assert track_saved_first.user_id == spotify_user_session.user.id
        assert track_saved_first.name == "Honey"
        assert track_saved_first.popularity == 48
        assert track_saved_first.is_saved is True
        assert track_saved_first.is_top is False
        assert track_saved_first.top_position is None
        assert len(track_saved_first.artists) == 1
        assert track_saved_first.artists[0].provider_id == "54kCbQZaZWHnwwj9VP2hn4"
        assert track_saved_first.artists[0].name == "Zola"
        assert track_saved_first.provider == MusicProvider.SPOTIFY
        assert track_saved_first.provider_id == "5GZPHysxDmjSAtXN87D78S"

        track_saved_last = tracks_saved[-1]
        assert track_saved_last.id is not None
        assert track_saved_last.user_id == spotify_user_session.user.id
        assert track_saved_last.name == "Magnum"
        assert track_saved_last.popularity == 36
        assert track_saved_last.is_saved is True
        assert track_saved_last.is_top is False
        assert track_saved_last.top_position is None
        assert len(track_saved_last.artists) == 1
        assert track_saved_last.artists[0].provider_id == "2kXKa3aAFngGz2P4GjG5w2"
        assert track_saved_last.artists[0].name == "SCH"
        assert track_saved_last.provider == MusicProvider.SPOTIFY
        assert track_saved_last.provider_id == "4nKcfnZ2Qj5urw0ekrnF2M"
