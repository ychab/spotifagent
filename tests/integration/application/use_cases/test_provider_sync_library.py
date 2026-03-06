import json
from typing import Any
from typing import Final

from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import pytest

from museflow.application.use_cases.provider_sync_library import ProviderSyncLibraryUseCase
from museflow.application.use_cases.provider_sync_library import SyncConfig
from museflow.application.use_cases.provider_sync_library import SyncReport
from museflow.domain.entities.auth import OAuthProviderUserToken
from museflow.domain.entities.music import Artist
from museflow.domain.entities.music import Track
from museflow.domain.entities.user import User
from museflow.domain.ports.repositories.music import ArtistRepository
from museflow.domain.ports.repositories.music import TrackRepository
from museflow.infrastructure.adapters.database.models import Artist as ArtistModel
from museflow.infrastructure.adapters.database.models import Track as TrackModel
from museflow.infrastructure.adapters.providers.spotify.library import SpotifyLibraryAdapter

from tests import ASSETS_DIR
from tests.integration.factories.models.music import ArtistModelFactory
from tests.integration.factories.models.music import TrackModelFactory
from tests.integration.utils.wiremock import WireMockContext

# As defined by wiremock hardcoded templates.
DEFAULT_PAGINATION_SIZE: Final[int] = 5
DEFAULT_PAGINATION_MAX: Final[int] = 3
DEFAULT_PAGINATION_TOTAL: Final[int] = 15


def wiremock_response(filename: str) -> dict[str, Any]:
    filepath = ASSETS_DIR / "wiremock" / "spotify" / "__files" / f"{filename}.json"
    return json.loads(filepath.read_text())


class TestSpotifySyncMusic:
    @pytest.fixture
    def patch_playlist_tracks_response(self, spotify_wiremock: WireMockContext) -> None:
        playlist_items = []
        for page_number in range(1, 3):
            playlist_items += wiremock_response(f"playlists_page_{page_number}")["items"]

        wiremock_playlist_response = wiremock_response("playlists_page_1")
        wiremock_playlist_response["items"] = playlist_items
        wiremock_playlist_response["total"] = len(playlist_items)
        wiremock_playlist_response["limit"] = DEFAULT_PAGINATION_SIZE

        # Instead of having 2 pages of 1 playlist, convert it into 1 page of 2 playlists
        spotify_wiremock.create_mapping(
            method="GET",
            url_path="/me/playlists",
            status=200,
            query_params={
                "offset": 0,
                "limit": DEFAULT_PAGINATION_SIZE,
            },
            json_body=wiremock_playlist_response,
        )

        playlist_track_map: dict[str, Any] = {
            "playlist_items_0wKgiV47itigJyxBgFxAu1": wiremock_playlist_response["items"][0],
            "playlist_items_1xnKqEZDpMWvrts4M9I9GC": wiremock_playlist_response["items"][1],
        }
        for template, playlist in playlist_track_map.items():
            playlist_track_items = []
            for page_number in range(1, 3):
                playlist_track_items += wiremock_response(f"{template}_page_{page_number}")["items"]

            wiremock_playlist_track_response = wiremock_response(f"{template}_page_1")
            wiremock_playlist_track_response["items"] = playlist_track_items
            wiremock_playlist_track_response["total"] = len(playlist_track_items)
            wiremock_playlist_track_response["limit"] = DEFAULT_PAGINATION_SIZE

            # Instead of having 2 playlist items pages of 1 track, convert it into 1 page of 2 tracks
            spotify_wiremock.create_mapping(
                method="GET",
                url_path=f"/playlists/{playlist['id']}/items",
                status=200,
                query_params={
                    "offset": 0,
                    "limit": DEFAULT_PAGINATION_SIZE,
                    "fields": "total,limit,offset,items(item(id,name,href,popularity,is_local,artists(id,name)))",
                    "additional_types": "track",
                },
                json_body=wiremock_playlist_track_response,
            )

    @pytest.fixture
    async def artists_update(self, request: pytest.FixtureRequest, user: User) -> list[Artist]:
        artists: list[Artist] = []

        page_max = getattr(request, "param", DEFAULT_PAGINATION_MAX)
        for page_number in range(1, page_max + 1):
            for item in wiremock_response(f"top_artists_page_{page_number}")["items"]:
                artist = await ArtistModelFactory.create_async(user_id=user.id, provider_id=item["id"])
                artists.append(artist.to_entity())

        return artists

    @pytest.fixture
    async def artists_top_delete(self, user: User) -> list[Artist]:
        return [artist.to_entity() for artist in await ArtistModelFactory.create_batch_async(size=3, user_id=user.id)]

    @pytest.fixture
    async def tracks_top_update(self, request: pytest.FixtureRequest, user: User) -> list[Track]:
        tracks: list[Track] = []
        page_max = getattr(request, "param", DEFAULT_PAGINATION_MAX)

        for page_number in range(1, page_max + 1):
            for item in wiremock_response(f"top_tracks_page_{page_number}")["items"]:
                track = await TrackModelFactory.create_async(
                    user_id=user.id,
                    provider_id=item["id"],
                    is_top=True,
                    is_saved=False,
                )
                tracks.append(track.to_entity())

        return tracks

    @pytest.fixture
    async def tracks_saved_update(self, request: pytest.FixtureRequest, user: User) -> list[Track]:
        tracks: list[Track] = []
        page_max = getattr(request, "param", DEFAULT_PAGINATION_MAX)

        for page_number in range(1, page_max + 1):
            for item in wiremock_response(f"saved_tracks_page_{page_number}")["items"]:
                track = await TrackModelFactory.create_async(
                    user_id=user.id,
                    provider_id=item["track"]["id"],
                    is_top=False,
                    is_saved=True,
                )
                tracks.append(track.to_entity())

        return tracks

    @pytest.fixture
    async def tracks_playlist_update(self, request: pytest.FixtureRequest, user: User) -> list[Track]:
        tracks: list[Track] = []
        page_max = getattr(request, "param", 2)

        for page_number in range(1, page_max + 1):
            for template in ["playlist_items_0wKgiV47itigJyxBgFxAu1", "playlist_items_1xnKqEZDpMWvrts4M9I9GC"]:
                for item in wiremock_response(f"{template}_page_{page_number}")["items"]:
                    track = await TrackModelFactory.create_async(
                        user_id=user.id,
                        provider_id=item["item"]["id"],
                        is_top=False,
                        is_saved=False,
                    )
                    tracks.append(track.to_entity())

        return tracks

    @pytest.fixture
    async def tracks_delete(self, user: User) -> list[Track]:
        tracks_top = await TrackModelFactory.create_batch_async(size=3, user_id=user.id, is_top=True, is_saved=False)
        tracks_saved = await TrackModelFactory.create_batch_async(size=2, user_id=user.id, is_top=False, is_saved=True)
        tracks_playlist = await TrackModelFactory.create_batch_async(
            size=4, user_id=user.id, is_top=False, is_saved=False
        )
        tracks_other = await TrackModelFactory.create_batch_async(size=1)

        return [track.to_entity() for track in tracks_top + tracks_saved + tracks_playlist + tracks_other]

    @pytest.fixture
    def use_case(
        self,
        spotify_library: SpotifyLibraryAdapter,
        artist_repository: ArtistRepository,
        track_repository: TrackRepository,
    ) -> ProviderSyncLibraryUseCase:
        return ProviderSyncLibraryUseCase(
            provider_library=spotify_library,
            artist_repository=artist_repository,
            track_repository=track_repository,
        )

    async def test__artists__purge(
        self,
        async_session_db: AsyncSession,
        user: User,
        auth_token: OAuthProviderUserToken,
        artists_top_delete: list[Artist],
        use_case: ProviderSyncLibraryUseCase,
    ) -> None:
        pass
        report = await use_case.execute(
            user=user,
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
        auth_token: OAuthProviderUserToken,
        tracks_delete: list[Track],
        purge_track_top: bool,
        purge_track_saved: bool,
        purge_track_playlist: bool,
        expected_purged_track: int,
        use_case: ProviderSyncLibraryUseCase,
    ) -> None:
        expected_other = 1
        total_user = len(tracks_delete) - expected_other

        report = await use_case.execute(
            user=user,
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
        use_case: ProviderSyncLibraryUseCase,
    ) -> None:
        page_size = DEFAULT_PAGINATION_SIZE
        expected_count = DEFAULT_PAGINATION_TOTAL

        report = await use_case.execute(
            user=user,
            config=SyncConfig(
                sync_artist_top=True,
                page_size=page_size,
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
        use_case: ProviderSyncLibraryUseCase,
    ) -> None:
        page_size = DEFAULT_PAGINATION_SIZE
        expected_count = len(artists_update)

        report = await use_case.execute(
            user=user,
            config=SyncConfig(
                sync_artist_top=True,
                page_size=page_size,
            ),
        )
        assert report == SyncReport(artist_updated=expected_count)

        stmt = select(ArtistModel).where(ArtistModel.user_id == user.id)
        result = await async_session_db.execute(stmt)
        artists_db = result.scalars().all()

        assert len(artists_db) == expected_count == 15
        assert sorted([a.id for a in artists_db]) == sorted([a.id for a in artists_update])

    async def test__tracks_top__sync__create(
        self,
        async_session_db: AsyncSession,
        user: User,
        use_case: ProviderSyncLibraryUseCase,
    ) -> None:
        page_size = DEFAULT_PAGINATION_SIZE
        expected_count = DEFAULT_PAGINATION_TOTAL

        report = await use_case.execute(
            user=user,
            config=SyncConfig(
                sync_track_top=True,
                page_size=page_size,
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
        use_case: ProviderSyncLibraryUseCase,
    ) -> None:
        page_size = DEFAULT_PAGINATION_SIZE
        expected_count = len(tracks_top_update)

        report = await use_case.execute(
            user=user,
            config=SyncConfig(
                sync_track_top=True,
                page_size=page_size,
            ),
        )
        assert report == SyncReport(track_updated=expected_count)

        stmt = select(TrackModel).where(TrackModel.user_id == user.id)
        result = await async_session_db.execute(stmt)
        tracks_db = result.scalars().all()

        assert len(tracks_db) == expected_count == 15
        assert sorted([t.id for t in tracks_db]) == sorted([t.id for t in tracks_top_update])

        assert all([track.is_top for track in tracks_db])
        assert not all([track.is_saved for track in tracks_db])

    async def test__tracks_saved__sync__create(
        self,
        async_session_db: AsyncSession,
        user: User,
        use_case: ProviderSyncLibraryUseCase,
    ) -> None:
        page_size = DEFAULT_PAGINATION_SIZE
        expected_count = DEFAULT_PAGINATION_TOTAL

        report = await use_case.execute(
            user=user,
            config=SyncConfig(
                sync_track_saved=True,
                page_size=page_size,
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
        use_case: ProviderSyncLibraryUseCase,
    ) -> None:
        page_size = DEFAULT_PAGINATION_SIZE
        expected_count = len(tracks_saved_update)

        report = await use_case.execute(
            user=user,
            config=SyncConfig(
                sync_track_saved=True,
                page_size=page_size,
            ),
        )
        assert report == SyncReport(track_updated=expected_count)

        stmt = select(TrackModel).where(TrackModel.user_id == user.id)
        result = await async_session_db.execute(stmt)
        tracks_db = result.scalars().all()

        assert len(tracks_db) == expected_count == 15
        assert sorted([t.id for t in tracks_db]) == sorted([t.id for t in tracks_saved_update])

        assert not all([track.is_top for track in tracks_db])
        assert all([track.is_saved for track in tracks_db])

    async def test__tracks_playlist__sync__create(
        self,
        async_session_db: AsyncSession,
        user: User,
        use_case: ProviderSyncLibraryUseCase,
    ) -> None:
        page_size = 1
        playlist_total = 2 * 1
        playlist_tracks_total = 2 * 1

        expected_count = playlist_total * playlist_tracks_total

        report = await use_case.execute(
            user=user,
            config=SyncConfig(
                sync_track_playlist=True,
                page_size=page_size,
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
        use_case: ProviderSyncLibraryUseCase,
    ) -> None:
        page_size = 1
        expected_count = len(tracks_playlist_update)

        report = await use_case.execute(
            user=user,
            config=SyncConfig(
                sync_track_playlist=True,
                page_size=page_size,
            ),
        )
        assert report == SyncReport(track_updated=expected_count)

        stmt = select(TrackModel).where(TrackModel.user_id == user.id)
        result = await async_session_db.execute(stmt)
        tracks_db = result.scalars().all()

        assert len(tracks_db) == expected_count == 4
        assert sorted([t.id for t in tracks_db]) == sorted([t.id for t in tracks_playlist_update])

        assert not all([track.is_top for track in tracks_db])
        assert not all([track.is_saved for track in tracks_db])

    async def test__all__purge__sync(
        self,
        async_session_db: AsyncSession,
        user: User,
        artists_top_delete: list[Artist],
        tracks_delete: list[Track],
        patch_playlist_tracks_response: None,
        use_case: ProviderSyncLibraryUseCase,
    ) -> None:
        expect_artists = DEFAULT_PAGINATION_TOTAL
        expected_tracks_top = DEFAULT_PAGINATION_TOTAL
        expected_tracks_saved = DEFAULT_PAGINATION_TOTAL
        expected_tracks_playlist = 2 * 2
        expect_tracks = expected_tracks_top + expected_tracks_saved + expected_tracks_playlist

        report = await use_case.execute(
            user=user,
            config=SyncConfig(
                purge_all=True,
                sync_all=True,
                page_size=DEFAULT_PAGINATION_SIZE,
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
        [(2, 2, 1, 1)],
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
        patch_playlist_tracks_response: None,
        use_case: ProviderSyncLibraryUseCase,
    ) -> None:
        """
        Given
          - A pagination of 3 pages of 5 top artists with 2 pages of top artists which already exists in DB
            -> 1 page * 5 items = 5 top artists created
            -> 2 pages * 5 items = 10 top artists updated
            -> total = 5 + 10 = 15 artists processed

          - A pagination of 3 pages of 5 top tracks with 2 pages of top tracks which already exists in DB
            -> 1 page * 5 items = 5 top tracks created
            -> 2 pages * 5 items = 10 top tracks updated
            -> total = 5 + 10 = 15 top tracks processed

          - A pagination of 3 pages of 5 saved tracks with 1 page of saved tracks which already exists in DB
            -> 2 pages * 5 items = 10 saved tracks created
            -> 1 page * 5 items = 5 saved tracks updated
            -> total = 10 + 5 = 15 saved tracks processed

          - A pagination of 1 page of 5 playlists
            -> 1 page * 2 items = 2 playlists

            - And for each playlist, 1 pages of 2 playlist tracks with 1 updated track (over the 2 tracks)
              -> 2 playlists * 1 page * 2 item = 4 playlist tracks processed total
              -> 2 playlists * 1 = 2 tracks created
              -> 2 playlists * 1 = 2 tracks updated
        When
          executing the sync with existing data in DB
        Then
          it will:
            - create 5 top artists
            - update 10 top artists
            - create 17 tracks (5 top + 10 saved + 2 playlist)
            - update 17 tracks (10 top + 5 saved + 2 playlist)

          and finally, in the DB, we will have:
            - 5 (created) + 10 (updated) = 15 top artists
            - 17 (created) + 17 (updated) = 34 tracks
        """
        page_size = DEFAULT_PAGINATION_SIZE

        # Then collects expectations.
        expect_artists_updated = len(artists_update)  # 10
        expect_artists_created = DEFAULT_PAGINATION_TOTAL - expect_artists_updated  # 5

        expect_tracks_top_updated = len(tracks_top_update)  # 10
        expect_tracks_top_created = DEFAULT_PAGINATION_TOTAL - expect_tracks_top_updated  # 5

        expect_tracks_saved_updated = len(tracks_saved_update)  # 5
        expect_tracks_saved_created = DEFAULT_PAGINATION_TOTAL - expect_tracks_saved_updated  # 10

        expect_tracks_playlist_updated = len(tracks_playlist_update)  # 2
        expect_tracks_playlist_created = 4 - len(tracks_playlist_update)  # 2

        expect_tracks_created = (  # 17
            expect_tracks_top_created + expect_tracks_saved_created + expect_tracks_playlist_created
        )
        expect_tracks_updated = (  # 17
            expect_tracks_top_updated + expect_tracks_saved_updated + expect_tracks_playlist_updated
        )

        report = await use_case.execute(
            user=user,
            config=SyncConfig(
                purge_all=False,
                sync_all=True,
                page_size=page_size,
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
        assert count == expect_tracks_created + expect_tracks_updated
