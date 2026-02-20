import copy
import json
import re
import uuid
from typing import Any
from typing import Final

from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import pytest
from pytest_httpx import HTTPXMock

from spotifagent.application.services.spotify import SpotifySessionFactory
from spotifagent.application.use_cases.spotify_sync import SyncConfig
from spotifagent.application.use_cases.spotify_sync import SyncReport
from spotifagent.application.use_cases.spotify_sync import spotify_sync
from spotifagent.domain.entities.music import Artist
from spotifagent.domain.entities.music import Track
from spotifagent.domain.entities.spotify import SpotifyTokenState
from spotifagent.domain.entities.users import User
from spotifagent.domain.ports.repositories.music import ArtistRepositoryPort
from spotifagent.domain.ports.repositories.music import TrackRepositoryPort
from spotifagent.infrastructure.adapters.clients.spotify import SpotifyClientAdapter
from spotifagent.infrastructure.adapters.database.models import Artist as ArtistModel
from spotifagent.infrastructure.adapters.database.models import Track as TrackModel

from tests import ASSETS_DIR
from tests.integration.factories.music import ArtistModelFactory
from tests.integration.factories.music import TrackModelFactory
from tests.integration.factories.users import UserModelFactory

DEFAULT_PAGINATION_LIMIT: Final[int] = 2
DEFAULT_PAGINATION_TOTAL: Final[int] = 10


def load_spotify_response(filename: str) -> dict[str, Any]:
    filepath = ASSETS_DIR / "httpmock" / "spotify" / f"{filename}.json"
    return json.loads(filepath.read_text())


def paginate_spotify_response(
    spotify_response: dict[str, Any],
    limit: int,
    total: int,
    offset: int = 0,
    size: int | None = None,
) -> list[dict[str, Any]]:
    response_chunks: list[dict[str, Any]] = []

    while offset + limit <= (size or total):
        response_chunk = copy.deepcopy(spotify_response)
        response_chunk["offset"] = offset
        response_chunk["limit"] = limit
        response_chunk["total"] = total
        response_chunk["items"] = response_chunk["items"][offset : offset + limit]

        response_chunks.append(response_chunk)
        offset += limit

    return response_chunks


class TestSpotifySync:
    @pytest.fixture
    def mock_refresh_token_endpoint(
        self,
        httpx_mock: HTTPXMock,
        spotify_session_factory: SpotifySessionFactory,
        token_state: SpotifyTokenState,
    ) -> SpotifyTokenState:
        httpx_mock.add_response(
            url=str(spotify_session_factory.spotify_client.token_endpoint),
            method="POST",
            json={
                "token_type": token_state.token_type,
                "access_token": token_state.access_token,
                "refresh_token": token_state.refresh_token,
                "expires_in": 3600,
            },
        )
        return token_state

    @pytest.fixture
    def artists_top_response(self) -> dict[str, Any]:
        return load_spotify_response(filename="top_artists")

    @pytest.fixture
    def artists_top_response_paginated(
        self,
        request: pytest.FixtureRequest,
        artists_top_response: dict[str, Any],
    ) -> list[dict[str, Any]]:
        params = getattr(request, "param", {})
        total: int = params.get("total", DEFAULT_PAGINATION_TOTAL)
        limit: int = params.get("limit", DEFAULT_PAGINATION_LIMIT)

        return paginate_spotify_response(artists_top_response, limit=limit, total=total)

    @pytest.fixture
    def tracks_top_response(self) -> dict[str, Any]:
        return load_spotify_response(filename="top_tracks")

    @pytest.fixture
    def tracks_top_response_paginated(
        self,
        request: pytest.FixtureRequest,
        tracks_top_response: dict[str, Any],
    ) -> list[dict[str, Any]]:
        params = getattr(request, "param", {})
        total: int = params.get("total", DEFAULT_PAGINATION_TOTAL)
        limit: int = params.get("limit", DEFAULT_PAGINATION_LIMIT)

        return paginate_spotify_response(tracks_top_response, limit=limit, total=total)

    @pytest.fixture
    def tracks_saved_response(self) -> dict[str, Any]:
        return load_spotify_response(filename="saved_tracks")

    @pytest.fixture
    def tracks_saved_response_paginated(
        self,
        request: pytest.FixtureRequest,
        tracks_saved_response: dict[str, Any],
    ) -> list[dict[str, Any]]:
        params = getattr(request, "param", {})
        total: int = params.get("total", DEFAULT_PAGINATION_TOTAL)
        limit: int = params.get("limit", DEFAULT_PAGINATION_LIMIT)

        return paginate_spotify_response(tracks_saved_response, limit=limit, total=total)

    @pytest.fixture
    def playlist_response(self) -> dict[str, Any]:
        return load_spotify_response(filename="playlists")

    @pytest.fixture
    def playlist_response_paginated(
        self,
        request: pytest.FixtureRequest,
        playlist_response: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], int, int]:
        params = getattr(request, "param", {})
        total: int = params.get("total", 4)
        limit: int = params.get("limit", DEFAULT_PAGINATION_LIMIT)

        return paginate_spotify_response(playlist_response, limit=limit, total=total), limit, total

    @pytest.fixture
    def playlist_tracks_response(self) -> dict[str, Any]:
        return load_spotify_response(filename="playlist_items")

    @pytest.fixture
    def playlist_tracks_response_paginated(
        self,
        request: pytest.FixtureRequest,
        playlist_response_paginated: tuple[list[dict[str, Any]], int, int],
        playlist_tracks_response: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], int, int]:
        responses: list[dict[str, Any]] = []

        params = getattr(request, "param", {})
        prevent_collision: bool = params.get("prevent_collision", False)

        playlist_limit = playlist_response_paginated[1]
        playlist_total = playlist_response_paginated[2]

        total: int = playlist_limit * 3
        offset: int = 0
        for _ in range(playlist_total):
            responses += paginate_spotify_response(
                playlist_tracks_response,
                limit=playlist_limit,
                total=total,
                offset=offset,
                size=total + offset,
            )
            offset += total

        # For creation tests, we can't have duplicate with other sources (top and saved)
        if prevent_collision:
            for response in responses:
                for page in response["items"]:
                    page["item"]["id"] = f"fake-provider-id-{uuid.uuid4()}"

        return responses, playlist_limit, total

    @pytest.fixture
    async def user(self) -> User:
        user_db = await UserModelFactory.create_async(with_spotify_account=True)
        return User.model_validate(user_db)

    @pytest.fixture
    async def artists_update(
        self,
        request: pytest.FixtureRequest,
        user: User,
        artists_top_response_paginated: list[dict[str, Any]],
    ) -> list[Artist]:
        page_max = getattr(request, "param", len(artists_top_response_paginated))
        artists: list[Artist] = []

        for page in artists_top_response_paginated[:page_max]:
            for item in page["items"]:
                artist = await ArtistModelFactory.create_async(user_id=user.id, provider_id=item["id"])
                artists.append(Artist.model_validate(artist))

        return artists

    @pytest.fixture
    async def artists_top_delete(self, user: User) -> list[Artist]:
        return [
            Artist.model_validate(artist)
            for artist in await ArtistModelFactory.create_batch_async(size=3, user_id=user.id)
        ]

    @pytest.fixture
    async def tracks_top_update(
        self,
        request: pytest.FixtureRequest,
        user: User,
        tracks_top_response_paginated: list[dict[str, Any]],
    ) -> list[Track]:
        page_max = getattr(request, "param", len(tracks_top_response_paginated))
        tracks: list[Track] = []

        for page in tracks_top_response_paginated[:page_max]:
            for item in page["items"]:
                track = await TrackModelFactory.create_async(
                    user_id=user.id,
                    provider_id=item["id"],
                    is_top=True,
                    is_saved=False,
                )
                tracks.append(Track.model_validate(track))

        return tracks

    @pytest.fixture
    async def tracks_saved_update(
        self,
        request: pytest.FixtureRequest,
        user: User,
        tracks_saved_response_paginated: list[dict[str, Any]],
    ) -> list[Track]:
        page_max = getattr(request, "param", len(tracks_saved_response_paginated))
        tracks: list[Track] = []

        for page in tracks_saved_response_paginated[:page_max]:
            for item in page["items"]:
                track = await TrackModelFactory.create_async(
                    user_id=user.id,
                    provider_id=item["track"]["id"],
                    is_top=False,
                    is_saved=True,
                )
                tracks.append(Track.model_validate(track))

        return tracks

    @pytest.fixture
    async def tracks_playlist_update(
        self,
        request: pytest.FixtureRequest,
        user: User,
        playlist_tracks_response_paginated: tuple[list[dict[str, Any]], int],
    ) -> list[Track]:
        tracks: list[Track] = []

        page_max = getattr(request, "param", len(playlist_tracks_response_paginated[0]))

        for page in playlist_tracks_response_paginated[0][:page_max]:
            for item in page["items"]:
                track, _ = await TrackModelFactory.get_or_create(
                    user_id=user.id,
                    provider_id=item["item"]["id"],
                    is_top=False,
                    is_saved=False,
                )
                tracks.append(Track.model_validate(track))

        return tracks

    @pytest.fixture
    async def tracks_delete(self, user: User) -> list[Track]:
        tracks_top = await TrackModelFactory.create_batch_async(size=3, user_id=user.id, is_top=True, is_saved=False)
        tracks_saved = await TrackModelFactory.create_batch_async(size=2, user_id=user.id, is_top=False, is_saved=True)
        tracks_playlist = await TrackModelFactory.create_batch_async(
            size=4, user_id=user.id, is_top=False, is_saved=False
        )
        tracks_other = await TrackModelFactory.create_batch_async(size=1)

        return [Track.model_validate(track) for track in tracks_top + tracks_saved + tracks_playlist + tracks_other]

    async def test__artists__purge(
        self,
        async_session_db: AsyncSession,
        user: User,
        artists_top_delete: list[Artist],
        spotify_session_factory: SpotifySessionFactory,
        artist_repository: ArtistRepositoryPort,
        track_repository: TrackRepositoryPort,
    ) -> None:
        pass
        report = await spotify_sync(
            user=user,
            spotify_session_factory=spotify_session_factory,
            artist_repository=artist_repository,
            track_repository=track_repository,
            config=SyncConfig(purge_artist_top=True),
        )
        assert report == SyncReport(purge_artist=len(artists_top_delete))

        stmt = select(func.count()).select_from(ArtistModel).where(ArtistModel.user_id == user.id)
        result = await async_session_db.execute(stmt)
        assert result.scalar() == 0

    @pytest.mark.parametrize(
        ("purge_track_top", "purge_track_saved", "purge_track_playlist", "expected_purged_track"),
        [
            (True, False, False, 3),
            (False, True, False, 2),
            (False, False, True, 4),
            (True, True, False, 5),
            (True, True, True, 9),
        ],
    )
    async def test__tracks__purge(
        self,
        async_session_db: AsyncSession,
        user: User,
        tracks_delete: list[Track],
        purge_track_top: bool,
        purge_track_saved: bool,
        purge_track_playlist: bool,
        expected_purged_track: int,
        spotify_session_factory: SpotifySessionFactory,
        artist_repository: ArtistRepositoryPort,
        track_repository: TrackRepositoryPort,
    ) -> None:
        expected_other = 1
        total_user = len(tracks_delete) - expected_other

        report = await spotify_sync(
            user=user,
            spotify_session_factory=spotify_session_factory,
            artist_repository=artist_repository,
            track_repository=track_repository,
            config=SyncConfig(
                purge_track_top=purge_track_top,
                purge_track_saved=purge_track_saved,
                purge_track_playlist=purge_track_playlist,
            ),
        )
        assert report == SyncReport(purge_track=expected_purged_track)

        stmt = select(func.count()).select_from(TrackModel).where(TrackModel.user_id == user.id)
        result = await async_session_db.execute(stmt)
        remaining_count = result.scalar()
        assert remaining_count == total_user - expected_purged_track

    async def test__artists_top__sync__create(
        self,
        async_session_db: AsyncSession,
        user: User,
        spotify_client: SpotifyClientAdapter,
        spotify_session_factory: SpotifySessionFactory,
        artist_repository: ArtistRepositoryPort,
        track_repository: TrackRepositoryPort,
        mock_refresh_token_endpoint: SpotifyTokenState,
        httpx_mock: HTTPXMock,
        artists_top_response: dict[str, Any],
        artists_top_response_paginated: list[dict[str, Any]],
    ) -> None:
        page_limit = DEFAULT_PAGINATION_LIMIT
        expected_count = DEFAULT_PAGINATION_TOTAL

        url_pattern = re.compile(r".*/me/top/artists.*")
        for response in artists_top_response_paginated:
            httpx_mock.add_response(
                url=url_pattern,
                method="GET",
                json=response,
            )

        report = await spotify_sync(
            user=user,
            spotify_session_factory=spotify_session_factory,
            artist_repository=artist_repository,
            track_repository=track_repository,
            config=SyncConfig(
                sync_artist_top=True,
                page_limit=page_limit,
            ),
        )
        assert report == SyncReport(artist_created=expected_count)

        stmt = select(func.count()).select_from(ArtistModel).where(ArtistModel.user_id == user.id)
        result = await async_session_db.execute(stmt)
        assert result.scalar() == expected_count

    async def test__artists_top__sync__update(
        self,
        async_session_db: AsyncSession,
        user: User,
        artists_update: list[Artist],
        spotify_client: SpotifyClientAdapter,
        spotify_session_factory: SpotifySessionFactory,
        artist_repository: ArtistRepositoryPort,
        track_repository: TrackRepositoryPort,
        mock_refresh_token_endpoint: SpotifyTokenState,
        httpx_mock: HTTPXMock,
        artists_top_response_paginated: list[dict[str, Any]],
    ) -> None:
        page_limit = DEFAULT_PAGINATION_LIMIT
        expected_count = len(artists_update)

        url_pattern = re.compile(r".*/me/top/artists.*")
        for response in artists_top_response_paginated:
            httpx_mock.add_response(
                url=url_pattern,
                method="GET",
                json=response,
            )

        report = await spotify_sync(
            user=user,
            spotify_session_factory=spotify_session_factory,
            artist_repository=artist_repository,
            track_repository=track_repository,
            config=SyncConfig(
                sync_artist_top=True,
                page_limit=page_limit,
            ),
        )
        assert report == SyncReport(artist_updated=expected_count)

        stmt = select(ArtistModel).where(ArtistModel.user_id == user.id)
        result = await async_session_db.execute(stmt)
        artists_db = result.scalars().all()

        assert len(artists_db) == expected_count
        assert sorted([a.id for a in artists_db]) == sorted([a.id for a in artists_update])

    async def test__tracks_top__sync__create(
        self,
        async_session_db: AsyncSession,
        user: User,
        spotify_client: SpotifyClientAdapter,
        spotify_session_factory: SpotifySessionFactory,
        artist_repository: ArtistRepositoryPort,
        track_repository: TrackRepositoryPort,
        mock_refresh_token_endpoint: SpotifyTokenState,
        httpx_mock: HTTPXMock,
        tracks_top_response: dict[str, Any],
        tracks_top_response_paginated: list[dict[str, Any]],
    ) -> None:
        page_limit = DEFAULT_PAGINATION_LIMIT
        expected_count = DEFAULT_PAGINATION_TOTAL

        url_pattern = re.compile(r".*/me/top/tracks.*")
        for response in tracks_top_response_paginated:
            httpx_mock.add_response(
                url=url_pattern,
                method="GET",
                json=response,
            )

        report = await spotify_sync(
            user=user,
            spotify_session_factory=spotify_session_factory,
            artist_repository=artist_repository,
            track_repository=track_repository,
            config=SyncConfig(
                sync_track_top=True,
                page_limit=page_limit,
            ),
        )
        assert report == SyncReport(track_created=expected_count)

        stmt = select(TrackModel).where(TrackModel.user_id == user.id)
        result = await async_session_db.execute(stmt)
        tracks_db = result.scalars().all()

        assert len(tracks_db) == expected_count
        assert all([track.is_top for track in tracks_db])
        assert not all([track.is_saved for track in tracks_db])

    async def test__tracks_top__sync__update(
        self,
        async_session_db: AsyncSession,
        user: User,
        tracks_top_update: list[Track],
        spotify_client: SpotifyClientAdapter,
        spotify_session_factory: SpotifySessionFactory,
        artist_repository: ArtistRepositoryPort,
        track_repository: TrackRepositoryPort,
        mock_refresh_token_endpoint: SpotifyTokenState,
        httpx_mock: HTTPXMock,
        tracks_top_response_paginated: list[dict[str, Any]],
    ) -> None:
        page_limit = DEFAULT_PAGINATION_LIMIT
        expected_count = len(tracks_top_update)

        url_pattern = re.compile(r".*/me/top/tracks.*")
        for response in tracks_top_response_paginated:
            httpx_mock.add_response(
                url=url_pattern,
                method="GET",
                json=response,
            )

        report = await spotify_sync(
            user=user,
            spotify_session_factory=spotify_session_factory,
            artist_repository=artist_repository,
            track_repository=track_repository,
            config=SyncConfig(
                sync_track_top=True,
                page_limit=page_limit,
            ),
        )
        assert report == SyncReport(track_updated=expected_count)

        stmt = select(TrackModel).where(TrackModel.user_id == user.id)
        result = await async_session_db.execute(stmt)
        tracks_db = result.scalars().all()

        assert len(tracks_db) == expected_count
        assert sorted([t.id for t in tracks_db]) == sorted([t.id for t in tracks_top_update])

        assert all([track.is_top for track in tracks_db])
        assert not all([track.is_saved for track in tracks_db])

    async def test__tracks_saved__sync__create(
        self,
        async_session_db: AsyncSession,
        user: User,
        spotify_client: SpotifyClientAdapter,
        spotify_session_factory: SpotifySessionFactory,
        artist_repository: ArtistRepositoryPort,
        track_repository: TrackRepositoryPort,
        mock_refresh_token_endpoint: SpotifyTokenState,
        httpx_mock: HTTPXMock,
        tracks_saved_response: dict[str, Any],
        tracks_saved_response_paginated: list[dict[str, Any]],
    ) -> None:
        page_limit = DEFAULT_PAGINATION_LIMIT
        expected_count = DEFAULT_PAGINATION_TOTAL

        url_pattern = re.compile(r".*/me/tracks.*")
        for response in tracks_saved_response_paginated:
            httpx_mock.add_response(
                url=url_pattern,
                method="GET",
                json=response,
            )

        report = await spotify_sync(
            user=user,
            spotify_session_factory=spotify_session_factory,
            artist_repository=artist_repository,
            track_repository=track_repository,
            config=SyncConfig(
                sync_track_saved=True,
                page_limit=page_limit,
            ),
        )
        assert report == SyncReport(track_created=expected_count)

        stmt = select(TrackModel).where(TrackModel.user_id == user.id)
        result = await async_session_db.execute(stmt)
        tracks_db = result.scalars().all()

        assert len(tracks_db) == expected_count
        assert not all([track.is_top for track in tracks_db])
        assert all([track.is_saved for track in tracks_db])

    async def test__tracks_saved__sync__update(
        self,
        async_session_db: AsyncSession,
        user: User,
        tracks_saved_update: list[Track],
        spotify_client: SpotifyClientAdapter,
        spotify_session_factory: SpotifySessionFactory,
        artist_repository: ArtistRepositoryPort,
        track_repository: TrackRepositoryPort,
        mock_refresh_token_endpoint: SpotifyTokenState,
        httpx_mock: HTTPXMock,
        tracks_saved_response_paginated: list[dict[str, Any]],
    ) -> None:
        page_limit = DEFAULT_PAGINATION_LIMIT
        expected_count = len(tracks_saved_update)

        url_pattern = re.compile(r".*/me/tracks.*")
        for response in tracks_saved_response_paginated:
            httpx_mock.add_response(
                url=url_pattern,
                method="GET",
                json=response,
            )

        report = await spotify_sync(
            user=user,
            spotify_session_factory=spotify_session_factory,
            artist_repository=artist_repository,
            track_repository=track_repository,
            config=SyncConfig(
                sync_track_saved=True,
                page_limit=page_limit,
            ),
        )
        assert report == SyncReport(track_updated=expected_count)

        stmt = select(TrackModel).where(TrackModel.user_id == user.id)
        result = await async_session_db.execute(stmt)
        tracks_db = result.scalars().all()

        assert len(tracks_db) == expected_count
        assert sorted([t.id for t in tracks_db]) == sorted([t.id for t in tracks_saved_update])

        assert not all([track.is_top for track in tracks_db])
        assert all([track.is_saved for track in tracks_db])

    async def test__tracks_playlist__sync__create(
        self,
        async_session_db: AsyncSession,
        user: User,
        spotify_client: SpotifyClientAdapter,
        spotify_session_factory: SpotifySessionFactory,
        artist_repository: ArtistRepositoryPort,
        track_repository: TrackRepositoryPort,
        mock_refresh_token_endpoint: SpotifyTokenState,
        httpx_mock: HTTPXMock,
        playlist_response_paginated: tuple[list[dict[str, Any]], int, int],
        playlist_tracks_response_paginated: tuple[list[dict[str, Any]], int, int],
    ) -> None:
        limit = playlist_response_paginated[1]
        playlist_total = playlist_response_paginated[2]
        playlist_tracks_total = playlist_tracks_response_paginated[2]

        expected_count = playlist_total * playlist_tracks_total

        url_pattern = re.compile(r".*/me/playlists.*")
        for response in playlist_response_paginated[0]:
            httpx_mock.add_response(
                url=url_pattern,
                method="GET",
                json=response,
            )

        url_pattern = re.compile(r".*/playlists/.*/items.*")
        for response in playlist_tracks_response_paginated[0]:
            httpx_mock.add_response(
                url=url_pattern,
                method="GET",
                json=response,
            )

        report = await spotify_sync(
            user=user,
            spotify_session_factory=spotify_session_factory,
            artist_repository=artist_repository,
            track_repository=track_repository,
            config=SyncConfig(
                sync_track_playlist=True,
                page_limit=limit,
            ),
        )
        assert report == SyncReport(track_created=expected_count)

        stmt = select(TrackModel).where(TrackModel.user_id == user.id)
        result = await async_session_db.execute(stmt)
        tracks_db = result.scalars().all()

        assert len(tracks_db) == expected_count
        assert not all([track.is_top for track in tracks_db])
        assert not all([track.is_saved for track in tracks_db])

    async def test__tracks_playlist__sync__update(
        self,
        async_session_db: AsyncSession,
        user: User,
        tracks_playlist_update: list[Track],
        spotify_client: SpotifyClientAdapter,
        spotify_session_factory: SpotifySessionFactory,
        artist_repository: ArtistRepositoryPort,
        track_repository: TrackRepositoryPort,
        mock_refresh_token_endpoint: SpotifyTokenState,
        httpx_mock: HTTPXMock,
        playlist_response_paginated: tuple[list[dict[str, Any]], int, int],
        playlist_tracks_response_paginated: tuple[list[dict[str, Any]], int, int],
    ) -> None:
        expected_count = len(tracks_playlist_update)

        url_pattern = re.compile(r".*/me/playlists.*")
        for response in playlist_response_paginated[0]:
            httpx_mock.add_response(
                url=url_pattern,
                method="GET",
                json=response,
            )

        url_pattern = re.compile(r".*/playlists/.*/items.*")
        for response in playlist_tracks_response_paginated[0]:
            httpx_mock.add_response(
                url=url_pattern,
                method="GET",
                json=response,
            )

        report = await spotify_sync(
            user=user,
            spotify_session_factory=spotify_session_factory,
            artist_repository=artist_repository,
            track_repository=track_repository,
            config=SyncConfig(
                sync_track_playlist=True,
                page_limit=playlist_response_paginated[1],
            ),
        )
        assert report == SyncReport(track_updated=expected_count)

        stmt = select(TrackModel).where(TrackModel.user_id == user.id)
        result = await async_session_db.execute(stmt)
        tracks_db = result.scalars().all()

        assert len(tracks_db) == expected_count
        assert sorted([t.id for t in tracks_db]) == sorted([t.id for t in tracks_playlist_update])

        assert not all([track.is_top for track in tracks_db])
        assert not all([track.is_saved for track in tracks_db])

    @pytest.mark.parametrize("playlist_tracks_response_paginated", [{"prevent_collision": True}], indirect=True)
    async def test__all__purge__sync(
        self,
        async_session_db: AsyncSession,
        user: User,
        artists_top_delete: list[Artist],
        tracks_delete: list[Track],
        spotify_client: SpotifyClientAdapter,
        spotify_session_factory: SpotifySessionFactory,
        artist_repository: ArtistRepositoryPort,
        track_repository: TrackRepositoryPort,
        mock_refresh_token_endpoint: SpotifyTokenState,
        httpx_mock: HTTPXMock,
        artists_top_response: dict[str, Any],
        artists_top_response_paginated: list[dict[str, Any]],
        tracks_top_response: dict[str, Any],
        tracks_top_response_paginated: list[dict[str, Any]],
        tracks_saved_response: dict[str, Any],
        tracks_saved_response_paginated: list[dict[str, Any]],
        playlist_response_paginated: tuple[list[dict[str, Any]], int, int],
        playlist_tracks_response_paginated: tuple[list[dict[str, Any]], int, int],
    ) -> None:
        url_artist_pattern = re.compile(r".*/me/top/artists.*")
        url_track_top_pattern = re.compile(r".*/me/top/tracks.*")
        url_track_saved_pattern = re.compile(r".*/me/tracks.*")
        url_playlist_pattern = re.compile(r".*/me/playlists.*")
        url_playlist_items_pattern = re.compile(r".*/playlists/.*/items.*")

        for response in artists_top_response_paginated:
            httpx_mock.add_response(
                url=url_artist_pattern,
                method="GET",
                json=response,
            )

        for response in tracks_top_response_paginated:
            httpx_mock.add_response(
                url=url_track_top_pattern,
                method="GET",
                json=response,
            )

        for response in tracks_saved_response_paginated:
            httpx_mock.add_response(
                url=url_track_saved_pattern,
                method="GET",
                json=response,
            )

        for response in playlist_response_paginated[0]:
            httpx_mock.add_response(
                url=url_playlist_pattern,
                method="GET",
                json=response,
            )

        for response in playlist_tracks_response_paginated[0]:
            httpx_mock.add_response(
                url=url_playlist_items_pattern,
                method="GET",
                json=response,
            )

        expect_artists = DEFAULT_PAGINATION_TOTAL
        expected_tracks_top = DEFAULT_PAGINATION_TOTAL
        expected_tracks_saved = DEFAULT_PAGINATION_TOTAL
        expected_tracks_playlist = playlist_response_paginated[2] * playlist_tracks_response_paginated[2]
        expect_tracks = expected_tracks_top + expected_tracks_saved + expected_tracks_playlist

        report = await spotify_sync(
            user=user,
            spotify_session_factory=spotify_session_factory,
            artist_repository=artist_repository,
            track_repository=track_repository,
            config=SyncConfig(
                purge=True,
                sync=True,
                page_limit=playlist_tracks_response_paginated[1],
            ),
        )
        assert report == SyncReport(
            purge_artist=len(artists_top_delete),
            purge_track=len(tracks_delete) - 1,  # Remove other use
            artist_created=expect_artists,
            track_created=expect_tracks,
        )

        stmt = select(func.count()).select_from(ArtistModel).where(ArtistModel.user_id == user.id)
        result = await async_session_db.execute(stmt)
        assert result.scalar() == expect_artists

        stmt_track = select(func.count()).select_from(TrackModel).where(TrackModel.user_id == user.id)
        result = await async_session_db.execute(stmt_track)
        assert result.scalar() == expect_tracks

        stmt = stmt_track.where(TrackModel.is_top.is_(True), TrackModel.is_saved.is_(False))
        result = await async_session_db.execute(stmt)
        assert result.scalar() == expected_tracks_top

        stmt = stmt_track.where(TrackModel.is_top.is_(False), TrackModel.is_saved.is_(True))
        result = await async_session_db.execute(stmt)
        assert result.scalar() == expected_tracks_saved

        stmt = stmt_track.where(TrackModel.is_top.is_(False), TrackModel.is_saved.is_(False))
        result = await async_session_db.execute(stmt)
        assert result.scalar() == expected_tracks_playlist

    @pytest.mark.parametrize(
        ("artists_update", "tracks_top_update", "tracks_saved_update", "tracks_playlist_update"),
        [(3, 2, 1, 1)],
        indirect=["artists_update", "tracks_top_update", "tracks_saved_update", "tracks_playlist_update"],
    )
    async def test__all__sync__update(
        self,
        async_session_db: AsyncSession,
        user: User,
        artists_update: list[Artist],
        tracks_top_update: list[Track],
        tracks_saved_update: list[Track],
        tracks_playlist_update: list[Track],
        spotify_client: SpotifyClientAdapter,
        spotify_session_factory: SpotifySessionFactory,
        artist_repository: ArtistRepositoryPort,
        track_repository: TrackRepositoryPort,
        mock_refresh_token_endpoint: SpotifyTokenState,
        httpx_mock: HTTPXMock,
        artists_top_response: dict[str, Any],
        artists_top_response_paginated: list[dict[str, Any]],
        tracks_top_response: dict[str, Any],
        tracks_top_response_paginated: list[dict[str, Any]],
        tracks_saved_response: dict[str, Any],
        tracks_saved_response_paginated: list[dict[str, Any]],
        playlist_response_paginated: tuple[list[dict[str, Any]], int, int],
        playlist_tracks_response_paginated: tuple[list[dict[str, Any]], int, int],
    ) -> None:
        """
        Given
          - A pagination of 5 pages of 2 top artists with 3 pages of top artists which already exists in DB
            -> 2 pages * 2 items = 4 top artists created
            -> 3 pages * 2 items = 6 top artists updated
            -> total = 4 + 6 = 10 artists processed

          - A pagination of 5 pages of 2 top tracks with 2 pages of top tracks which already exists in DB
            -> 3 pages * 2 items = 6 top tracks created
            -> 2 pages * 2 items = 4 top tracks updated
            -> total = 6 + 4 = 10 top tracks processed

          - A pagination of 5 pages of 2 saved tracks with 1 pages of saved tracks which already exists in DB
            -> 4 pages * 2 items = 8 saved tracks created
            -> 1 pages * 2 items = 2 saved tracks updated
            -> total = 8 + 2 = 10 saved tracks processed

          - A pagination of 2 pages of 2 playlists
            -> 2 pages * 2 items = 4 playlists

            - And for each playlist, 3 pages of 2 playlist tracks with 2 duplicate tracks over the 6 tracks
              -> 4 playlists * 3 pages * 2 items = 24 playlist tracks processed total
              -> 4 playlists * 2 duplicates (over 6 tracks) = 8 duplicates
              -> Then, it results to:
                -> 24 tracks - 8 duplicates = 16 playlist tracks created
                -> 8 duplicates found = 8 playlist tracks updated
        When
          executing the sync with existing data in DB
        Then
          it will:
            - create 4 top artists
            - update 6 top artists
            - create 30 tracks (6 top + 8 saved + 16 playlist)
            - update 14 tracks (4 top + 2 saved + 8 playlist)

          and finally in the DB, we will have:
            - 4 (initial) + 6 (created) = 10 top artists
            - 7 (initial) + 30 (created) = 37 tracks
              (Note: Initial = 4 top + 2 saved + 1 playlist = 7 pre-existing tracks)
        """
        page_limit = DEFAULT_PAGINATION_LIMIT

        url_artist_pattern = re.compile(r".*/me/top/artists.*")
        url_track_top_pattern = re.compile(r".*/me/top/tracks.*")
        url_track_saved_pattern = re.compile(r".*/me/tracks.*")
        url_playlist_pattern = re.compile(r".*/me/playlists.*")
        url_playlist_items_pattern = re.compile(r".*/playlists/.*/items.*")

        for response in artists_top_response_paginated:
            httpx_mock.add_response(
                url=url_artist_pattern,
                method="GET",
                json=response,
            )

        for response in tracks_top_response_paginated:
            httpx_mock.add_response(
                url=url_track_top_pattern,
                method="GET",
                json=response,
            )

        for response in tracks_saved_response_paginated:
            httpx_mock.add_response(
                url=url_track_saved_pattern,
                method="GET",
                json=response,
            )

        for response in playlist_response_paginated[0]:
            httpx_mock.add_response(
                url=url_playlist_pattern,
                method="GET",
                json=response,
            )

        for response in playlist_tracks_response_paginated[0]:
            httpx_mock.add_response(
                url=url_playlist_items_pattern,
                method="GET",
                json=response,
            )

        # Gather duplicate ids.
        track_top_created_ids = [item["id"] for page in tracks_top_response_paginated for item in page["items"]]
        track_saved_created_ids = [
            item["track"]["id"] for page in tracks_saved_response_paginated for item in page["items"]
        ]
        track_playlist_created_ids = [
            item["item"]["id"] for page in playlist_tracks_response_paginated[0] for item in page["items"]
        ]
        track_updated_ids = [t.provider_id for t in tracks_top_update + tracks_saved_update + tracks_playlist_update]
        track_existing_ids = set(track_updated_ids + track_top_created_ids + track_saved_created_ids)

        # Then collects expectations.
        expect_artists_updated = len(artists_update)  # 6
        expect_artists_created = DEFAULT_PAGINATION_TOTAL - expect_artists_updated  # 4

        expect_tracks_top_updated = len(tracks_top_update)  # 4
        expect_tracks_top_created = DEFAULT_PAGINATION_TOTAL - expect_tracks_top_updated  # 6

        expect_tracks_saved_updated = len(tracks_saved_update)  # 2
        expect_tracks_saved_created = DEFAULT_PAGINATION_TOTAL - expect_tracks_saved_updated  # 8

        expect_tracks_playlist_created = len(
            [pid for pid in track_playlist_created_ids if pid not in track_existing_ids]  # 16
        )
        expect_tracks_playlist_updated = len(track_playlist_created_ids) - expect_tracks_playlist_created  # 8

        expect_tracks_created = (
            expect_tracks_top_created + expect_tracks_saved_created + expect_tracks_playlist_created
        )
        expect_tracks_updated = (
            expect_tracks_top_updated + expect_tracks_saved_updated + expect_tracks_playlist_updated
        )

        report = await spotify_sync(
            user=user,
            spotify_session_factory=spotify_session_factory,
            artist_repository=artist_repository,
            track_repository=track_repository,
            config=SyncConfig(
                purge=False,
                sync=True,
                page_limit=page_limit,
            ),
        )
        assert report == SyncReport(
            artist_created=expect_artists_created,
            artist_updated=expect_artists_updated,
            track_created=expect_tracks_created,
            track_updated=expect_tracks_updated,
        )

        stmt = select(func.count()).select_from(ArtistModel).where(ArtistModel.user_id == user.id)
        result = await async_session_db.execute(stmt)
        count = result.scalar()
        assert count == expect_artists_created + expect_artists_updated

        stmt = select(func.count()).select_from(TrackModel).where(TrackModel.user_id == user.id)
        result = await async_session_db.execute(stmt)
        count = result.scalar()
        # Exclude tracks updated multiple times or were already in the DB.
        assert count == expect_tracks_created + len(set(track_updated_ids))
