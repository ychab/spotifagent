import uuid

import pytest

from tests.integration.factories.music import ArtistModelFactory
from tests.integration.factories.music import TrackModelFactory
from tests.integration.factories.users import UserModelFactory


class TestArtistModelFactory:
    @pytest.mark.parametrize(("name", "expected_slug"), [("Yé Ho", "ye-ho")])
    async def test__slug(self, name: str, expected_slug: str) -> None:
        artist_db = await ArtistModelFactory.create_async(name=name)
        assert artist_db.slug == expected_slug

    async def test__user__default(self) -> None:
        artist_db = await ArtistModelFactory.create_async()
        assert artist_db.user_id is not None

    async def test__user__provided(self) -> None:
        user_db = await UserModelFactory.create_async()
        artist_db = await ArtistModelFactory.create_async(user_id=user_db.id)
        assert artist_db.user_id == user_db.id


class TestTrackModelFactory:
    @pytest.mark.parametrize(("name", "expected_slug"), [("Yé Ho", "ye-ho")])
    async def test__slug(self, name: str, expected_slug: str) -> None:
        track_db = await TrackModelFactory.create_async(name=name)
        assert track_db.slug == expected_slug

    async def test__user__default(self) -> None:
        track_db = await TrackModelFactory.create_async()
        assert track_db.user_id is not None

    async def test__user__provided(self) -> None:
        user_db = await UserModelFactory.create_async()
        track_db = await TrackModelFactory.create_async(user_id=user_db.id)
        assert track_db.user_id == user_db.id

    async def test__get_or_create__get(self) -> None:
        track_existing_db = await TrackModelFactory.create_async()

        track_db, created = await TrackModelFactory.get_or_create(
            user_id=track_existing_db.user_id,
            provider_id=track_existing_db.provider_id,
        )
        assert track_db.id == track_existing_db.id
        assert track_db.provider_id == track_existing_db.provider_id
        assert created is False

    async def test__get_or_create__create(self) -> None:
        user_db = await UserModelFactory.create_async()
        provider_id = str(uuid.uuid4())

        track_db, created = await TrackModelFactory.get_or_create(
            user_id=user_db.id,
            provider_id=provider_id,
        )
        assert track_db.id is not None
        assert track_db.provider_id == provider_id
        assert created is True

    @pytest.mark.parametrize(
        ("user_id", "provider_id"),
        [
            ("", ""),
            ("foo-bar-baz", ""),
            ("", "foo-bar-baz"),
        ],
    )
    async def test__get_or_create__exception(self, user_id: uuid.UUID, provider_id: str) -> None:
        with pytest.raises(ValueError, match="You must provide 'user_id' and 'provider_id' for uniqueness."):
            await TrackModelFactory.get_or_create(user_id=user_id, provider_id=provider_id)
