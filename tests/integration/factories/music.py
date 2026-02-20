import uuid
from typing import Any
from typing import cast

from sqlalchemy import select

from polyfactory import Use
from polyfactory.decorators import post_generated
from slugify import slugify

from spotifagent.domain.entities.music import MusicProvider
from spotifagent.infrastructure.adapters.database.models import Artist
from spotifagent.infrastructure.adapters.database.models import Track

from tests.integration.factories.base import BaseModelFactory
from tests.integration.factories.users import UserModelFactory


class BaseMusicItemModelFactory[T: (Artist | Track)](BaseModelFactory[T]):
    __is_base_factory__ = True

    name = Use(BaseModelFactory.__faker__.name)

    popularity = Use(BaseModelFactory.__faker__.random_int, min=0, max=100)
    top_position = Use(BaseModelFactory.__faker__.random_int, min=1)

    provider = MusicProvider.SPOTIFY

    @post_generated
    @classmethod
    def slug(cls, name: str) -> str:
        return slugify(name)

    @classmethod
    async def create_async(cls, **kwargs: Any) -> T:
        if "user_id" not in kwargs:
            user = await UserModelFactory.create_async()
            kwargs["user_id"] = user.id

        return cast(T, await super().create_async(**kwargs))

    @classmethod
    async def create_batch_async(cls, size: int, **kwargs: Any) -> list[T]:
        if "user_id" not in kwargs:
            user = await UserModelFactory.create_async()
            kwargs["user_id"] = user.id

        return cast(list[T], await super().create_batch_async(size=size, **kwargs))


class ArtistModelFactory(BaseMusicItemModelFactory[Artist]):
    __model__ = Artist

    genres = Use(lambda: ["Pop", "Rock", "Rap", "Indie", "Alternative"])


class TrackModelFactory(BaseMusicItemModelFactory[Track]):
    __model__ = Track

    artists = Use(
        lambda: [
            {
                "name": BaseMusicItemModelFactory.__faker__.name(),
                "provider_id": str(uuid.uuid4()),
            }
            for _ in range(BaseMusicItemModelFactory.__faker__.random_int(min=1, max=3))
        ]
    )

    @classmethod
    async def get_or_create(cls, user_id: uuid.UUID, provider_id: str, **kwargs: Any) -> tuple[Track, bool]:
        if not user_id or not provider_id:
            raise ValueError("You must provide 'user_id' and 'provider_id' for uniqueness.")

        session = cls.__async_session__
        stmt = select(cls.__model__).filter_by(user_id=user_id, provider_id=provider_id)
        result = await session.execute(stmt)  # type: ignore[union-attr]
        instance = result.scalar_one_or_none()

        if instance:
            return instance, False

        instance = await cls.create_async(user_id=user_id, provider_id=provider_id, **kwargs)
        return instance, True
