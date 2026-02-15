import copy
import json
import re
from typing import Any
from typing import Final

from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import pytest
from pytest_httpx import HTTPXMock

from spotifagent.application.services.spotify import SpotifySessionFactory
from spotifagent.application.use_cases.spotify_sync import SyncReport
from spotifagent.application.use_cases.spotify_sync import spotify_sync
from spotifagent.domain.entities.music import Artist
from spotifagent.domain.entities.music import Track
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

DEFAULT_PAGINATION_LIMIT: Final[int] = 5
DEFAULT_PAGINATION_TOTAL: Final[int] = 20


def load_spotify_response(filename: str = "top_artists") -> dict[str, Any]:
    filepath = ASSETS_DIR / "httpmock" / "spotify" / f"{filename}.json"
    return json.loads(filepath.read_text())


def paginate_spotify_response(spotify_response: dict[str, Any]) -> list[dict[str, Any]]:
    response_chunks: list[dict[str, Any]] = []

    offset: int = 0
    limit: int = DEFAULT_PAGINATION_LIMIT
    total: int = DEFAULT_PAGINATION_TOTAL
    while offset + limit <= total:
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
    def artists_top_response(self) -> dict[str, Any]:
        return load_spotify_response(filename="top_artists")

    @pytest.fixture
    def artists_top_response_paginated(self, artists_top_response: dict[str, Any]) -> list[dict[str, Any]]:
        return paginate_spotify_response(artists_top_response)

    @pytest.fixture
    def tracks_top_response(self) -> dict[str, Any]:
        return load_spotify_response(filename="top_tracks")

    @pytest.fixture
    def tracks_top_response_paginated(self, tracks_top_response: dict[str, Any]) -> list[dict[str, Any]]:
        return paginate_spotify_response(tracks_top_response)

    @pytest.fixture
    def tracks_saved_response(self) -> dict[str, Any]:
        return load_spotify_response(filename="saved_tracks")

    @pytest.fixture
    def tracks_saved_response_paginated(self, tracks_saved_response: dict[str, Any]) -> list[dict[str, Any]]:
        return paginate_spotify_response(tracks_saved_response)

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
    async def tracks_delete(self, user: User) -> list[Track]:
        tracks_top = await TrackModelFactory.create_batch_async(size=3, user_id=user.id, is_top=True, is_saved=False)
        tracks_saved = await TrackModelFactory.create_batch_async(size=2, user_id=user.id, is_top=False, is_saved=True)
        tracks_other = await TrackModelFactory.create_batch_async(size=1)

        return [Track.model_validate(track) for track in tracks_top + tracks_saved + tracks_other]

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
            purge_artist_top=True,
        )
        assert report == SyncReport(purge_artist=len(artists_top_delete))

        stmt = select(func.count()).select_from(ArtistModel).where(ArtistModel.user_id == user.id)
        result = await async_session_db.execute(stmt)
        assert result.scalar() == 0

    @pytest.mark.parametrize(
        ("purge_track_top", "purge_track_saved", "expected_purged_track"),
        [
            (True, False, 3),
            (False, True, 2),
            (True, True, 5),
        ],
    )
    async def test__tracks__purge(
        self,
        async_session_db: AsyncSession,
        user: User,
        tracks_delete: list[Track],
        purge_track_top: bool,
        purge_track_saved: bool,
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
            purge_track_top=purge_track_top,
            purge_track_saved=purge_track_saved,
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
        httpx_mock: HTTPXMock,
        artists_top_response: dict[str, Any],
        artists_top_response_paginated: list[dict[str, Any]],
    ) -> None:
        expected_count = len(artists_top_response["items"])

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
            sync_artist_top=True,
            page_limit=len(artists_top_response_paginated),
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
        httpx_mock: HTTPXMock,
        artists_top_response_paginated: list[dict[str, Any]],
    ) -> None:
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
            sync_artist_top=True,
            page_limit=len(artists_top_response_paginated),
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
        httpx_mock: HTTPXMock,
        tracks_top_response: dict[str, Any],
        tracks_top_response_paginated: list[dict[str, Any]],
    ) -> None:
        expected_count = len(tracks_top_response["items"])

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
            sync_track_top=True,
            page_limit=len(tracks_top_response_paginated),
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
        httpx_mock: HTTPXMock,
        tracks_top_response_paginated: list[dict[str, Any]],
    ) -> None:
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
            sync_track_top=True,
            page_limit=len(tracks_top_response_paginated),
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
        httpx_mock: HTTPXMock,
        tracks_saved_response: dict[str, Any],
        tracks_saved_response_paginated: list[dict[str, Any]],
    ) -> None:
        expected_count = len(tracks_saved_response["items"])

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
            sync_track_saved=True,
            page_limit=len(tracks_saved_response_paginated),
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
        httpx_mock: HTTPXMock,
        tracks_saved_response_paginated: list[dict[str, Any]],
    ) -> None:
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
            sync_track_saved=True,
            page_limit=len(tracks_saved_response_paginated),
        )
        assert report == SyncReport(track_updated=expected_count)

        stmt = select(TrackModel).where(TrackModel.user_id == user.id)
        result = await async_session_db.execute(stmt)
        tracks_db = result.scalars().all()

        assert len(tracks_db) == expected_count
        assert sorted([t.id for t in tracks_db]) == sorted([t.id for t in tracks_saved_update])

        assert not all([track.is_top for track in tracks_db])
        assert all([track.is_saved for track in tracks_db])

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
        httpx_mock: HTTPXMock,
        artists_top_response: dict[str, Any],
        artists_top_response_paginated: list[dict[str, Any]],
        tracks_top_response: dict[str, Any],
        tracks_top_response_paginated: list[dict[str, Any]],
        tracks_saved_response: dict[str, Any],
        tracks_saved_response_paginated: list[dict[str, Any]],
    ) -> None:
        url_artist_pattern = re.compile(r".*/me/top/artists.*")
        url_track_top_pattern = re.compile(r".*/me/top/tracks.*")
        url_track_saved_pattern = re.compile(r".*/me/tracks.*")

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

        expect_artists = len(artists_top_response["items"])
        expect_tracks = len(tracks_top_response["items"]) + len(tracks_saved_response["items"])

        report = await spotify_sync(
            user=user,
            spotify_session_factory=spotify_session_factory,
            artist_repository=artist_repository,
            track_repository=track_repository,
            purge_artist_top=True,
            purge_track_top=True,
            purge_track_saved=True,
            sync_artist_top=True,
            sync_track_top=True,
            sync_track_saved=True,
            page_limit=len(tracks_top_response_paginated),
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

        stmt = select(func.count()).select_from(TrackModel).where(TrackModel.user_id == user.id)
        result = await async_session_db.execute(stmt)
        assert result.scalar() == expect_tracks

    @pytest.mark.parametrize(
        ("artists_update", "tracks_top_update", "tracks_saved_update"),
        [(3, 2, 1)],
        indirect=["artists_update", "tracks_top_update", "tracks_saved_update"],
    )
    async def test__all__sync__update(
        self,
        async_session_db: AsyncSession,
        user: User,
        artists_update: list[Artist],
        tracks_top_update: list[Track],
        tracks_saved_update: list[Track],
        spotify_client: SpotifyClientAdapter,
        spotify_session_factory: SpotifySessionFactory,
        artist_repository: ArtistRepositoryPort,
        track_repository: TrackRepositoryPort,
        httpx_mock: HTTPXMock,
        artists_top_response: dict[str, Any],
        artists_top_response_paginated: list[dict[str, Any]],
        tracks_top_response: dict[str, Any],
        tracks_top_response_paginated: list[dict[str, Any]],
        tracks_saved_response: dict[str, Any],
        tracks_saved_response_paginated: list[dict[str, Any]],
    ) -> None:
        url_artist_pattern = re.compile(r".*/me/top/artists.*")
        url_track_top_pattern = re.compile(r".*/me/top/tracks.*")
        url_track_saved_pattern = re.compile(r".*/me/tracks.*")

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

        expect_artists_created = int(
            ((DEFAULT_PAGINATION_TOTAL / DEFAULT_PAGINATION_LIMIT) - 3) * DEFAULT_PAGINATION_LIMIT
        )
        expect_tracks_top_created = int(
            ((DEFAULT_PAGINATION_TOTAL / DEFAULT_PAGINATION_LIMIT) - 2) * DEFAULT_PAGINATION_LIMIT
        )
        expect_tracks_saved_created = int(
            ((DEFAULT_PAGINATION_TOTAL / DEFAULT_PAGINATION_LIMIT) - 1) * DEFAULT_PAGINATION_LIMIT
        )
        expect_tracks_created = expect_tracks_top_created + expect_tracks_saved_created

        expect_artists_updated = 3 * DEFAULT_PAGINATION_LIMIT
        expect_tracks_updated = (2 * DEFAULT_PAGINATION_LIMIT) + (1 * DEFAULT_PAGINATION_LIMIT)

        report = await spotify_sync(
            user=user,
            spotify_session_factory=spotify_session_factory,
            artist_repository=artist_repository,
            track_repository=track_repository,
            sync_artist_top=True,
            sync_track_top=True,
            sync_track_saved=True,
            page_limit=len(tracks_top_response_paginated),
        )
        assert report == SyncReport(
            artist_created=expect_artists_created,
            artist_updated=expect_artists_updated,
            track_created=expect_tracks_created,
            track_updated=expect_tracks_updated,
        )

        stmt = select(func.count()).select_from(ArtistModel).where(ArtistModel.user_id == user.id)
        result = await async_session_db.execute(stmt)
        assert result.scalar() == expect_artists_created + expect_artists_updated

        stmt = select(func.count()).select_from(TrackModel).where(TrackModel.user_id == user.id)
        result = await async_session_db.execute(stmt)
        assert result.scalar() == expect_tracks_created + expect_tracks_updated
