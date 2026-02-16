import uuid
from abc import ABC
from abc import abstractmethod

from spotifagent.domain.entities.music import Artist
from spotifagent.domain.entities.music import Track


class ArtistRepositoryPort(ABC):
    @abstractmethod
    async def get_list(
        self,
        user_id: uuid.UUID,
        offset: int | None = None,
        limit: int | None = None,
    ) -> list[Artist]: ...

    @abstractmethod
    async def bulk_upsert(self, artists: list[Artist], batch_size: int) -> tuple[list[uuid.UUID], int]: ...

    @abstractmethod
    async def purge(self, user_id: uuid.UUID) -> int: ...


class TrackRepositoryPort(ABC):
    @abstractmethod
    async def get_list(
        self,
        user_id: uuid.UUID,
        offset: int | None = None,
        limit: int | None = None,
    ) -> list[Track]: ...

    @abstractmethod
    async def bulk_upsert(self, tracks: list[Track], batch_size: int) -> tuple[list[uuid.UUID], int]: ...

    @abstractmethod
    async def purge(
        self,
        user_id: uuid.UUID,
        is_top: bool = False,
        is_saved: bool = False,
        is_playlist: bool = False,
    ) -> int: ...
