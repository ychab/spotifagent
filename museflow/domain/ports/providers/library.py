from abc import ABC
from abc import abstractmethod

from museflow.domain.entities.music import Artist
from museflow.domain.entities.music import Playlist
from museflow.domain.entities.music import Track


class ProviderLibraryPort(ABC):
    """A port defining the contract for interacting with a music provider's library.

    This interface abstracts the retrieval of various music entities (artists, tracks)
    from a user's library on a specific music provider.
    """

    @abstractmethod
    async def get_top_artists(
        self,
        page_size: int,
        max_pages: int | None = None,
        time_range: str | None = None,
    ) -> list[Artist]:
        """Retrieves a list of the user's top artists from the music provider.

        Args:
            page_size: The maximum number of artists to retrieve per page.
            max_pages: The maximum number of playlist tracks pages to retrieve.
            time_range: An optional time frame for which to retrieve top artists

        Returns:
            A list of `Artist` entities.
        """
        ...

    @abstractmethod
    async def get_top_tracks(
        self,
        page_size: int,
        max_pages: int | None = None,
        time_range: str | None = None,
    ) -> list[Track]:
        """Retrieves a list of the user's top tracks from the music provider.

        Args:
            page_size: The maximum number of tracks to retrieve per page.
            max_pages: The maximum number of playlist tracks pages to retrieve.
            time_range: An optional time frame for which to retrieve top tracks

        Returns:
            A list of `Track` entities.
        """
        ...

    @abstractmethod
    async def get_saved_tracks(self, page_size: int, max_pages: int | None = None) -> list[Track]:
        """Retrieves a list of tracks saved (liked) by the user in their music library.

        Args:
            page_size: The maximum number of saved tracks to retrieve per page.
            max_pages: The maximum number of playlist tracks pages to retrieve.

        Returns:
            A list of `Track` entities.
        """
        ...

    @abstractmethod
    async def get_playlist_tracks(self, page_size: int, max_pages: int | None = None) -> list[Track]:
        """Retrieves a list of tracks from the user's playlists.

        Args:
            page_size: The maximum number of playlist tracks to retrieve per page.
            max_pages: The maximum number of playlist tracks pages to retrieve.

        Returns:
            A list of `Track` entities.
        """
        ...

    @abstractmethod
    async def search_tracks(
        self,
        track: str,
        artists: list[str] | None = None,
        genres: list[str] | None = None,
        is_new: bool = False,
        is_underground: bool = False,
        isrc: str | None = None,
        page_size: int = 20,
        max_pages: int | None = None,
    ) -> list[Track]:
        """Retrieves a list of tracks based on the search criteria.

        Args:
            track: The name of the track to search for.
            artists: A list of artist names to filter by.
            genres: A list of genres to filter by.
            is_new: Whether to include only new tracks (periodicity depends on the provider).
            is_underground: Whether to include underground tracks (depends on the provider).
            isrc: An optional ISRC (International Standard Recording Code) to filter by.
            page_size: An optional maximum number of tracks per page.
            max_pages: The maximum number of pages to retrieve.

        Returns:
            A list of `Track` entities.
        """
        ...

    @abstractmethod
    async def create_playlist(self, name: str, tracks: list[Track], is_public: bool = False) -> Playlist:
        """Create a user's playlist with the given tracks.

        Args:
            name: The name of the playlist
            tracks: A list of tracks to add to the playlist
            is_public: Whether the playlist should be public or private

        Returns:
            The entity's playlist created.
        """
        ...
