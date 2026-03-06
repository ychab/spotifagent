import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from museflow import __project_name__
from museflow.domain.entities.auth import OAuthProviderUserToken
from museflow.domain.entities.music import Artist
from museflow.domain.entities.music import BaseMediaItem
from museflow.domain.entities.music import Playlist
from museflow.domain.entities.music import Track
from museflow.domain.entities.user import User
from museflow.domain.exceptions import ProviderPageValidationError
from museflow.domain.ports.providers.library import ProviderLibraryPort
from museflow.domain.ports.repositories.auth import OAuthProviderTokenRepository
from museflow.infrastructure.adapters.providers.spotify.client import SpotifyOAuthClientAdapter
from museflow.infrastructure.adapters.providers.spotify.mappers import to_domain_artist
from museflow.infrastructure.adapters.providers.spotify.mappers import to_domain_playlist
from museflow.infrastructure.adapters.providers.spotify.mappers import to_domain_track
from museflow.infrastructure.adapters.providers.spotify.queries import SpotifySearchTrackQuery
from museflow.infrastructure.adapters.providers.spotify.schemas import SpotifyArtist
from museflow.infrastructure.adapters.providers.spotify.schemas import SpotifyItem
from museflow.infrastructure.adapters.providers.spotify.schemas import SpotifyPage
from museflow.infrastructure.adapters.providers.spotify.schemas import SpotifyPlaylist
from museflow.infrastructure.adapters.providers.spotify.schemas import SpotifyPlaylistTrack
from museflow.infrastructure.adapters.providers.spotify.schemas import SpotifySavedTrack
from museflow.infrastructure.adapters.providers.spotify.schemas import SpotifyTrack
from museflow.infrastructure.adapters.providers.spotify.session import SpotifyOAuthSessionClient
from museflow.infrastructure.adapters.providers.spotify.types import LocalUnsupported
from museflow.infrastructure.adapters.providers.spotify.types import SpotifyTimeRange
from museflow.infrastructure.config.settings.app import app_settings

logger = logging.getLogger(__name__)


@dataclass
class SpotifyLibraryFactory:
    """Factory responsible for creating `SpotifyLibraryAdapter` instances.

    This factory handles the dependency injection required to create a
    `SpotifyLibraryAdapter`, specifically wiring up the `SpotifyOAuthSessionClient`
    with the necessary repositories and clients.
    """

    auth_token_repository: OAuthProviderTokenRepository
    client: SpotifyOAuthClientAdapter

    def create(self, user: User, auth_token: OAuthProviderUserToken) -> ProviderLibraryPort:
        """Creates a new `SpotifyLibraryAdapter` for a specific user.

        Args:
            user: The user for whom the adapter is being created.
            auth_token: The user's OAuth token.

        Returns:
            A configured `ProviderLibraryPort` implementation for Spotify.
        """
        return SpotifyLibraryAdapter(
            user=user,
            session_client=SpotifyOAuthSessionClient(
                user=user,
                auth_token=auth_token,
                auth_token_repository=self.auth_token_repository,
                client=self.client,
            ),
        )


class SpotifyLibraryAdapter(ProviderLibraryPort):
    """Adapter for interacting with the Spotify Web API to retrieve library data.

    This class implements the `ProviderLibraryPort` interface, providing methods
    to fetch top artists, top tracks, saved tracks, and playlist tracks from
    Spotify. It handles pagination and concurrent fetching where appropriate.
    """

    def __init__(
        self,
        user: User,
        session_client: SpotifyOAuthSessionClient,
        max_concurrency: int = app_settings.SYNC_SEMAPHORE_MAX_CONCURRENCY,
    ) -> None:
        self.user = user
        self.session_client = session_client
        self.max_concurrency = max_concurrency

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    async def get_top_artists(
        self,
        page_size: int = 50,
        max_pages: int | None = None,
        time_range: SpotifyTimeRange | str | None = "long_term",
    ) -> list[Artist]:
        return await self._fetch_pages(
            endpoint="/me/top/artists",
            page_model=SpotifyPage[SpotifyArtist],
            page_processor=self._extract_top_artists,
            params={"time_range": time_range},
            page_size=page_size,
            max_pages=max_pages,
            prefix_log="[TopArtists]",
        )

    async def get_top_tracks(
        self,
        page_size: int = 50,
        max_pages: int | None = None,
        time_range: SpotifyTimeRange | str | None = "long_term",
    ) -> list[Track]:
        return await self._fetch_pages(
            endpoint="/me/top/tracks",
            page_model=SpotifyPage[SpotifyTrack],
            page_processor=self._extract_top_tracks,
            params={"time_range": time_range},
            page_size=page_size,
            max_pages=max_pages,
            prefix_log="[TopTracks]",
        )

    async def get_saved_tracks(self, page_size: int = 50, max_pages: int | None = None) -> list[Track]:
        return await self._fetch_pages(
            endpoint="/me/tracks",
            page_model=SpotifyPage[SpotifySavedTrack],
            page_processor=self._extract_saved_tracks,
            page_size=page_size,
            max_pages=max_pages,
            prefix_log="[SavedTracks]",
        )

    async def get_playlist_tracks(self, page_size: int = 50, max_pages: int | None = None) -> list[Track]:
        """Retrieves tracks from all of the user's playlists.

        This method first fetches all playlists and then fetches the tracks for
        each playlist concurrently, respecting the `max_concurrency` limit.
        """
        playlists = await self._fetch_pages(
            endpoint="/me/playlists",
            page_model=SpotifyPage[SpotifyPlaylist],
            page_processor=self._extract_playlists,
            page_size=page_size,
            max_pages=max_pages,
            prefix_log="[Playlists]",
        )
        logger.info(f"Found {len(playlists)} playlists. Fetching tracks...")

        # Use a Semaphore to limit concurrent playlist fetching to avoid rate limits and overwhelming resources.
        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def _fetch_with_semaphore(playlist: SpotifyPlaylist) -> list[Track]:
            async with semaphore:
                return await self._fetch_playlist_tracks(playlist, page_size, max_pages)

        # Fetch in parallel all playlist's tracks with a semaphore.
        async with asyncio.TaskGroup() as tg:
            tasks = [tg.create_task(_fetch_with_semaphore(playlist)) for playlist in playlists]

        # Gather all tracks first.
        tracks = [track for task in tasks for track in task.result()]
        # Then remove duplicates due to multiple playlists with the same tracks.
        return list({track.provider_id: track for track in tracks}.values())

    async def search_tracks(
        self,
        track: str,
        artists: list[str] | None = None,
        genres: list[str] | None = None,
        is_new: bool = False,
        is_underground: bool = False,
        isrc: str | None = None,
        page_size: int = 10,
        max_pages: int | None = None,
    ) -> list[Track]:
        query_builder = SpotifySearchTrackQuery(
            track=track,
            artists=artists or [],
            genres=genres or [],
            is_new=is_new,
            is_underground=is_underground,
            isrc=isrc,
        )

        return await self._fetch_pages(
            endpoint="/search",
            page_model=SpotifyPage[SpotifyTrack],
            page_processor=self._extract_search_tracks,
            page_size=page_size,
            max_pages=max_pages,
            prefix_log=f"[Search track {track}]",
            params={
                "q": query_builder.get_query(),
                "type": "track",
            },
            response_key="tracks",
        )

    async def create_playlist(self, name: str, tracks: list[Track], is_public: bool = False) -> Playlist:
        # First, create the playlist
        data = await self._execute_request(
            method="POST",
            endpoint="/me/playlists",
            json_data={
                "name": name,
                "public": is_public,
                "collaborative": False,
                "description": f"Auto-generated by {__project_name__}",
            },
        )
        spotify_playlist = SpotifyPlaylist.model_validate(data)

        # Then, insert the playlist tracks.
        data = await self._execute_request(
            method="POST",
            endpoint=f"/playlists/{spotify_playlist.id}/items",
            json_data={
                "uris": [f"spotify:track:{track.provider_id}" for track in tracks],
            },
        )
        spotify_playlist.snapshot_id = data["snapshot_id"]

        return to_domain_playlist(spotify_playlist, user_id=self.user.id, tracks=tracks)

    # -------------------------------------------------------------------------
    # Core Logic
    # -------------------------------------------------------------------------

    async def _fetch_playlist_tracks(
        self,
        playlist: SpotifyPlaylist,
        page_size: int,
        max_pages: int | None = None,
    ) -> list[Track]:
        tracks: list[Track] = []

        try:
            tracks = await self._fetch_pages(
                endpoint=f"/playlists/{playlist.id}/items",
                page_model=SpotifyPage[SpotifyPlaylistTrack],
                page_processor=self._extract_playlist_tracks,
                params={
                    "fields": "total,limit,offset,items(item(id,name,href,popularity,is_local,artists(id,name)))",
                    "additional_types": "track",
                },
                page_size=page_size,
                max_pages=max_pages,
                prefix_log=f"[PlaylistTracks({playlist.name})]",
            )
        except ProviderPageValidationError as e:
            # Some playlist pages can return invalid data, like missing ID's due to local files.
            # Anyway, we don't want to break the entire loop of playlists so we catch it here.
            logger.error(f"Skip playlist {playlist.name.strip()} with error: {e}")

        return tracks

    async def _fetch_pages[
        SpotifyItemType: SpotifyItem | SpotifySavedTrack | SpotifyPlaylistTrack,
        MediaItemType: BaseMediaItem | SpotifyPlaylist,
    ](
        self,
        endpoint: str,
        page_model: type[SpotifyPage[SpotifyItemType]],
        page_processor: Callable[[SpotifyPage[SpotifyItemType], int], list[MediaItemType]],
        method: str = "GET",
        params: dict[str, Any] | None = None,
        offset: int = 0,
        page_size: int = 50,
        max_pages: int | None = None,
        prefix_log: str = "",
        response_key: str | None = None,
    ) -> list[MediaItemType]:
        """
        Generic method to fetch paginated resources from Spotify.
        Iterates through pages until all items are retrieved or the page_size is reached.
        """
        items: list[MediaItemType] = []
        pages_count = 0

        logger.info(f"{prefix_log} Start fetching endpoint: {endpoint}")
        while True:
            if max_pages is not None and max_pages <= pages_count:
                break

            data = await self._execute_request(
                method=method,
                endpoint=endpoint,
                params={
                    "offset": offset,
                    "limit": page_size,
                    **(params or {}),
                },
            )

            if response_key and response_key in data:
                data = data[response_key]

            try:
                page = page_model.model_validate(data)
            except ValidationError as e:
                has_local_files = any([error["type"] == LocalUnsupported for error in e.errors()])
                exc_msg = "Unsupported local files" if has_local_files else str(e)

                raise ProviderPageValidationError(
                    msg=f"{prefix_log} - Page validation error on {endpoint} (offset: {offset}): {exc_msg}",
                    code="unsupported_local_files" if has_local_files else None,
                ) from e

            items += page_processor(page, offset)
            pages_count += 1

            logger.info(f"{prefix_log} ... processed {offset + page_size}/{page.total} ...")
            if len(items) >= page.total or len(page.items) < page_size:
                break

            offset += page_size

        return items

    async def _execute_request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await self.session_client.execute(
            method=method,
            endpoint=endpoint,
            params=params,
            json_data=json_data,
        )

    # -------------------------------------------------------------------------
    # Extractors
    # -------------------------------------------------------------------------

    def _extract_playlists(self, page: SpotifyPage[SpotifyPlaylist], *_: Any) -> list[SpotifyPlaylist]:
        return list(page.items)

    def _extract_top_artists(self, page: SpotifyPage[SpotifyArtist], offset: int) -> list[Artist]:
        return [
            to_domain_artist(item, user_id=self.user.id, is_top=True, position=offset + i + 1)
            for i, item in enumerate(page.items)
        ]

    def _extract_top_tracks(self, page: SpotifyPage[SpotifyTrack], offset: int) -> list[Track]:
        return [
            to_domain_track(item, user_id=self.user.id, is_top=True, position=offset + i + 1)
            for i, item in enumerate(page.items)
        ]

    def _extract_saved_tracks(self, page: SpotifyPage[SpotifySavedTrack], *_: Any) -> list[Track]:
        return [to_domain_track(item.track, user_id=self.user.id, is_saved=True) for item in page.items]

    def _extract_playlist_tracks(self, page: SpotifyPage[SpotifyPlaylistTrack], *_: Any) -> list[Track]:
        return [to_domain_track(item.item, user_id=self.user.id) for item in page.items if item.item]

    def _extract_search_tracks(self, page: SpotifyPage[SpotifyTrack], *_: Any) -> list[Track]:
        return [to_domain_track(item, user_id=self.user.id) for item in page.items if item]
