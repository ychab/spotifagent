from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import pytest

from spotifagent.domain.entities.music import Artist
from spotifagent.domain.entities.music import Track
from spotifagent.domain.entities.users import User
from spotifagent.domain.ports.repositories.music import ArtistRepositoryPort
from spotifagent.domain.ports.repositories.music import TrackRepositoryPort
from spotifagent.infrastructure.adapters.database.models import Artist as ArtistModel
from spotifagent.infrastructure.adapters.database.models import Track as TrackModel

from tests.integration.factories.music import ArtistModelFactory
from tests.integration.factories.music import TrackModelFactory
from tests.unit.factories.music import ArtistFactory
from tests.unit.factories.music import TrackFactory


class TestArtistRepository:
    @pytest.fixture
    async def artists(self, user: User) -> list[Artist]:
        artists_db = await ArtistModelFactory.create_batch_async(size=10, user_id=user.id)
        return [Artist.model_validate(artist_db) for artist_db in artists_db]

    @pytest.fixture
    async def artists_other(self) -> list[Artist]:
        artists_db = await ArtistModelFactory.create_batch_async(size=2)
        return [Artist.model_validate(artist_db) for artist_db in artists_db]

    @pytest.fixture
    def artists_create(self, user: User) -> list[Artist]:
        return ArtistFactory.batch(size=10, user_id=user.id)

    @pytest.fixture
    def artists_update(self, artists: list[Artist]) -> list[Artist]:
        return [Artist.model_validate({**artist.model_dump(), "genres": ["foo"]}) for artist in artists]

    @pytest.fixture
    def artists_mix(self, user: User, artists: list[Artist]) -> list[Artist]:
        return [
            *ArtistFactory.batch(size=5, user_id=user.id),  # 5 created
            *[  # 5 updated
                Artist.model_validate({**artist.model_dump(), "genres": ["foo"]}) for artist in artists[:5]
            ],
        ]

    @pytest.fixture
    async def artists_delete(self, user: User) -> list[Artist]:
        artists_user = await ArtistModelFactory.create_batch_async(size=3, user_id=user.id)
        artists_others = await ArtistModelFactory.create_batch_async(size=2)

        return [Artist.model_validate(artist_db) for artist_db in artists_user + artists_others]

    @pytest.mark.parametrize(("offset", "limit"), [(None, None), (2, 5)])
    async def test__get_list__nominal(
        self,
        user: User,
        offset: int | None,
        limit: int | None,
        artists: list[Artist],
        artists_other: list[Artist],
        artist_repository: ArtistRepositoryPort,
    ) -> None:
        artists_expected = artists[offset : offset + limit] if offset is not None and limit is not None else artists

        artist_list = await artist_repository.get_list(user.id, offset=offset, limit=limit)

        # Check that we have the expected items.
        assert len(artist_list) == len(artists_expected)
        assert sorted([a.provider_id for a in artist_list]) == sorted([str(a.provider_id) for a in artists_expected])

        # Check that items have been collected only for that user.
        assert set([a.user_id for a in artist_list]) == {user.id}

    async def test__bulk_upsert__create(
        self,
        async_session_db: AsyncSession,
        user: User,
        artists_create: list[Artist],
        artist_repository: ArtistRepositoryPort,
    ) -> None:
        artist_ids, create_count = await artist_repository.bulk_upsert(
            artists_create,
            batch_size=int(len(artists_create) / 5),
        )

        # Check that we have the expected number of items.
        assert len(artist_ids) == len(artists_create) == create_count == 10

        # Check that objects has been really created in DB.
        stmt = select(ArtistModel).where(ArtistModel.id.in_(artist_ids))
        results = await async_session_db.execute(stmt)
        artists_db = results.scalars().all()
        assert len(artists_db) == len(artist_ids)

        # Check that items have been created only for that user.
        assert set([a.user_id for a in artists_db]) == {user.id}
        # Check that at least one field was inserted as expected.
        assert sorted([a.provider_id for a in artists_db]) == sorted([str(a.provider_id) for a in artists_create])

    async def test__bulk_upsert__update(
        self,
        async_session_db: AsyncSession,
        user: User,
        artists: list[Artist],
        artists_update: list[Artist],
        artist_repository: ArtistRepositoryPort,
    ) -> None:
        artist_ids, create_count = await artist_repository.bulk_upsert(
            artists_update,
            batch_size=int(len(artists_update) / 5),
        )

        # Check that we have the expected number of items.
        assert len(artist_ids) == len(artists_update) == len(artists) == 10
        assert create_count == 0

        # Check that objects has been really updated in DB.
        stmt = select(ArtistModel).where(ArtistModel.id.in_(artist_ids))
        results = await async_session_db.execute(stmt)
        artists_db = results.scalars().all()
        assert len(artists_db) == len(artists_update)

        # Check that items have been created only for that user.
        assert set([a.user_id for a in artists_db]) == {user.id}
        # Check that at least one field was updated as expected.
        assert set([artist_db.genres[0] for artist_db in artists_db]) == {"foo"}

    async def test__bulk_upsert__both(
        self,
        async_session_db: AsyncSession,
        user: User,
        artists_mix: list[Artist],
        artist_repository: ArtistRepositoryPort,
    ) -> None:
        artist_ids, create_count = await artist_repository.bulk_upsert(artists_mix, 300)

        # Check that we have the expected number of items.
        assert len(artist_ids) == len(artists_mix) == 10
        assert create_count == 5

        # Check that objects has been really updated in DB.
        stmt = select(ArtistModel).where(ArtistModel.id.in_(artist_ids)).order_by(ArtistModel.created_at.asc())
        results = await async_session_db.execute(stmt)
        artists_db = results.scalars().all()
        assert len(artists_db) == len(artists_mix)

        # Check that items have been upserted only for that user.
        assert set([a.user_id for a in artists_db]) == {user.id}

        # Check created as expected.
        assert sorted([a.provider_id for a in artists_db[:5]]) == sorted([str(a.provider_id) for a in artists_mix[:5]])
        # Check updated as expected.
        assert set([a.genres[0] for a in artists_db[5:]]) == {"foo"}

    async def test__purge(
        self,
        async_session_db: AsyncSession,
        user: User,
        artists_delete: list[Artist],
        artist_repository: ArtistRepositoryPort,
    ) -> None:
        count = await artist_repository.purge(user.id)
        assert count == 3

        # Check if all artists have been deleted for that user.
        stmt = select(func.count()).select_from(ArtistModel).where(ArtistModel.user_id == user.id)
        results = await async_session_db.execute(stmt)
        assert results.scalar() == 0

        # Be sure to keep other users items!
        stmt = select(func.count()).select_from(ArtistModel).where(ArtistModel.user_id != user.id)
        results = await async_session_db.execute(stmt)
        assert results.scalar() == 2


class TestTrackRepository:
    @pytest.fixture
    async def tracks(self, user: User) -> list[Track]:
        tracks_db = await TrackModelFactory.create_batch_async(size=10, user_id=user.id)
        return [Track.model_validate(track_db) for track_db in tracks_db]

    @pytest.fixture
    async def tracks_other(self) -> list[Track]:
        tracks_db = await TrackModelFactory.create_batch_async(size=2)
        return [Track.model_validate(track_db) for track_db in tracks_db]

    @pytest.fixture
    def tracks_create(self, user: User) -> list[Track]:
        return TrackFactory.batch(size=10, user_id=user.id)

    @pytest.fixture
    def tracks_update(self, tracks) -> list[Track]:
        return [
            Track.model_validate({**track.model_dump(), "artists": [{"name": "SCH", "provider_id": "foo"}]})
            for track in tracks
        ]

    @pytest.fixture
    def tracks_mix(self, user: User, tracks) -> list[Track]:
        return [
            *TrackFactory.batch(size=5, user_id=user.id),  # 5 created
            *[
                Track.model_validate({**track.model_dump(), "artists": [{"name": "SCH", "provider_id": "foo"}]})
                for track in tracks[:5]
            ],  # 5 updated
        ]

    @pytest.fixture
    async def tracks_delete(self, user: User) -> list[Track]:
        tracks_top = await TrackModelFactory.create_batch_async(
            size=4,
            user_id=user.id,
            is_top=True,
            is_saved=False,
        )
        tracks_saved = await TrackModelFactory.create_batch_async(
            size=3,
            user_id=user.id,
            is_top=False,
            is_saved=True,
        )
        tracks_playlist = await TrackModelFactory.create_batch_async(
            size=2,
            user_id=user.id,
            is_top=False,
            is_saved=False,
        )
        tracks_others = await TrackModelFactory.create_batch_async(size=1)

        return [
            Track.model_validate(track_db) for track_db in tracks_top + tracks_saved + tracks_playlist + tracks_others
        ]

    @pytest.mark.parametrize(("offset", "limit"), [(None, None), (2, 5)])
    async def test__get_list__nominal(
        self,
        user: User,
        offset: int | None,
        limit: int | None,
        tracks: list[Track],
        tracks_other: list[Track],
        track_repository: TrackRepositoryPort,
    ) -> None:
        tracks_expected = tracks[offset : offset + limit] if offset is not None and limit is not None else tracks

        track_list = await track_repository.get_list(user.id, offset=offset, limit=limit)

        # Check that we have the expected items.
        assert len(track_list) == len(tracks_expected)
        assert set([t.provider_id for t in track_list]).issubset([t.provider_id for t in tracks])
        assert sorted([t.provider_id for t in track_list]) == sorted([str(t.provider_id) for t in tracks_expected])

        # Check that items have been collected only for that user.
        assert set([t.user_id for t in track_list]) == {user.id}

    async def test__bulk_upsert__create(
        self,
        async_session_db: AsyncSession,
        user: User,
        tracks_create: list[Track],
        track_repository: TrackRepositoryPort,
    ) -> None:
        track_ids, create_count = await track_repository.bulk_upsert(
            tracks_create,
            batch_size=int(len(tracks_create) / 5),
        )

        # Check that we have the expected number of items.
        assert len(track_ids) == len(tracks_create) == create_count == 10

        # Check that objects has been really created in DB.
        stmt = select(TrackModel).where(TrackModel.id.in_(track_ids))
        results = await async_session_db.execute(stmt)
        tracks_db = results.scalars().all()

        assert len(tracks_db) == len(track_ids)
        assert set([t.user_id for t in tracks_db]) == {user.id}
        assert sorted([t.provider_id for t in tracks_db]) == sorted([str(t.provider_id) for t in tracks_create])

    async def test__bulk_upsert__update(
        self,
        async_session_db: AsyncSession,
        user: User,
        tracks: list[Track],
        tracks_update: list[Track],
        track_repository: TrackRepositoryPort,
    ) -> None:
        track_ids, create_count = await track_repository.bulk_upsert(
            tracks_update,
            batch_size=int(len(tracks_update) / 5),
        )

        # Check that we have the expected number of items.
        assert len(track_ids) == len(tracks_update) == len(tracks) == 10
        assert create_count == 0

        # Check that objects has been really updated in DB.
        stmt = select(TrackModel).where(TrackModel.id.in_(track_ids))
        results = await async_session_db.execute(stmt)
        tracks_db = results.scalars().all()

        assert len(tracks_db) == len(tracks_update)
        assert set([t.user_id for t in tracks_db]) == {user.id}

        artists = [track_db.artists[0] for track_db in tracks_db]
        expected_artists = [{"name": "SCH", "provider_id": "foo"} for _ in range(len(tracks_db))]
        assert artists == expected_artists

    async def test__bulk_upsert__both(
        self,
        async_session_db: AsyncSession,
        user: User,
        tracks_mix: list[Track],
        track_repository: TrackRepositoryPort,
    ) -> None:
        track_ids, create_count = await track_repository.bulk_upsert(tracks_mix, 300)

        # Check that we have the expected number of items.
        assert len(track_ids) == len(tracks_mix) == 10
        assert create_count == 5

        # Check that objects has been really updated in DB.
        stmt = select(TrackModel).where(TrackModel.id.in_(track_ids)).order_by(TrackModel.created_at.asc())
        results = await async_session_db.execute(stmt)
        tracks_db = results.scalars().all()
        assert len(tracks_db) == len(tracks_mix)
        assert set([t.user_id for t in tracks_db]) == {user.id}

        # Check created as expected.
        assert sorted([t.provider_id for t in tracks_db[:5]]) == sorted([str(t.provider_id) for t in tracks_mix[:5]])
        # Check updated as expected.
        artists = [track_db.artists[0] for track_db in tracks_db[5:]]
        expected_artists = [{"name": "SCH", "provider_id": "foo"} for _ in range(len(tracks_db[5:]))]
        assert artists == expected_artists

    @pytest.mark.parametrize(
        ("is_top", "is_saved", "is_playlist", "expected_count"),
        [
            pytest.param(False, False, False, 4 + 3 + 2, id="all_implicit"),
            pytest.param(True, False, False, 4 + 0 + 0, id="top_only"),
            pytest.param(False, True, False, 0 + 3 + 0, id="saved_only"),
            pytest.param(False, False, True, 0 + 0 + 2, id="playlist_only"),
            pytest.param(True, True, False, 4 + 3 + 0, id="top_and_saved"),
            pytest.param(True, False, True, 4 + 0 + 2, id="top_and_playlist"),
            pytest.param(False, True, True, 0 + 3 + 2, id="saved_and_playlist"),
            pytest.param(True, True, True, 4 + 3 + 2, id="all_explicit"),
        ],
    )
    async def test__purge(
        self,
        async_session_db: AsyncSession,
        user: User,
        tracks_delete: list[Track],
        is_top: bool,
        is_saved: bool,
        is_playlist: bool,
        expected_count: int,
        track_repository: TrackRepositoryPort,
    ) -> None:
        expected_other_count = 1
        expected_total_user_count = len(tracks_delete) - expected_other_count

        count = await track_repository.purge(user.id, is_top=is_top, is_saved=is_saved, is_playlist=is_playlist)
        assert count == expected_count

        # Check if all artists have been deleted for that user.
        stmt = select(func.count()).select_from(TrackModel).where(TrackModel.user_id == user.id)
        results = await async_session_db.execute(stmt)
        remaining_count = results.scalar()
        assert remaining_count == expected_total_user_count - expected_count

        # Be sure to keep other users items!
        stmt = select(func.count()).select_from(TrackModel).where(TrackModel.user_id != user.id)
        results = await async_session_db.execute(stmt)
        remaining_other_count = results.scalar()
        assert remaining_other_count == expected_other_count
