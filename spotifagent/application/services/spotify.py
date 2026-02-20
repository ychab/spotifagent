import asyncio
import logging
from collections.abc import Callable
from typing import Any
from typing import Literal

from pydantic import ValidationError

from spotifagent.domain.entities.music import Artist
from spotifagent.domain.entities.music import BaseMusicItem
from spotifagent.domain.entities.music import Track
from spotifagent.domain.entities.spotify import SpotifyArtist
from spotifagent.domain.entities.spotify import SpotifyPage
from spotifagent.domain.entities.spotify import SpotifyPlaylist
from spotifagent.domain.entities.spotify import SpotifyPlaylistPage
from spotifagent.domain.entities.spotify import SpotifyPlaylistTrackPage
from spotifagent.domain.entities.spotify import SpotifySavedTrackPage
from spotifagent.domain.entities.spotify import SpotifyTopArtistPage
from spotifagent.domain.entities.spotify import SpotifyTopTrackPage
from spotifagent.domain.entities.spotify import SpotifyTrack
from spotifagent.domain.entities.users import User
from spotifagent.domain.exceptions import SpotifyAccountNotFoundError
from spotifagent.domain.exceptions import SpotifyPageValidationError
from spotifagent.domain.ports.clients.spotify import SpotifyClientPort
from spotifagent.domain.ports.repositories.spotify import SpotifyAccountRepositoryPort
from spotifagent.infrastructure.config.settings.app import app_settings

TimeRange = Literal["short_term", "medium_term", "long_term"]

logger = logging.getLogger(__name__)


class SpotifySessionFactory:
    """
    Factory responsible for wiring up dependencies and validating
    that a user is eligible for a session.
    """

    def __init__(
        self,
        spotify_account_repository: SpotifyAccountRepositoryPort,
        spotify_client: SpotifyClientPort,
    ) -> None:
        self.spotify_account_repository = spotify_account_repository
        self.spotify_client = spotify_client

    def create(self, user: User) -> "SpotifyUserSession":
        if not user.spotify_account:
            raise SpotifyAccountNotFoundError(f"User {user.email} is not connected to Spotify.")

        return SpotifyUserSession(
            user=user,
            spotify_account_repository=self.spotify_account_repository,
            spotify_client=self.spotify_client,
        )


class SpotifyUserSession:
    """
    A service that binds a specific User to the SpotifyClient.
    It automatically handles token persistence side effects.
    """

    def __init__(
        self,
        user: User,
        spotify_account_repository: SpotifyAccountRepositoryPort,
        spotify_client: SpotifyClientPort,
        max_concurrency: int = app_settings.SYNC_SEMAPHORE_MAX_CONCURRENCY,
    ) -> None:
        self.user = user
        self.spotify_account_repository = spotify_account_repository
        self.spotify_client = spotify_client
        self.max_concurrency = max_concurrency

        self._is_token_refreshed: bool = False
        self._refresh_lock: asyncio.Lock = asyncio.Lock()

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    async def get_top_artists(self, limit: int = 50, time_range: TimeRange = "long_term") -> list[Artist]:
        return await self._fetch_pages(
            endpoint="/me/top/artists",
            page_model=SpotifyTopArtistPage,
            page_processor=self._extract_top_artists,
            params={"time_range": time_range},
            limit=limit,
            prefix_log="[TopArtists]",
        )

    async def get_top_tracks(self, limit: int = 50, time_range: TimeRange = "long_term") -> list[Track]:
        return await self._fetch_pages(
            endpoint="/me/top/tracks",
            page_model=SpotifyTopTrackPage,
            page_processor=self._extract_top_tracks,
            params={"time_range": time_range},
            limit=limit,
            prefix_log="[TopTracks]",
        )

    async def get_saved_tracks(self, limit: int = 50) -> list[Track]:
        return await self._fetch_pages(
            endpoint="/me/tracks",
            page_model=SpotifySavedTrackPage,
            page_processor=self._extract_saved_tracks,
            limit=limit,
            prefix_log="[SavedTracks]",
        )

    async def get_playlist_tracks(self, limit: int = 50) -> list[Track]:
        playlists = await self._fetch_pages(
            endpoint="/me/playlists",
            page_model=SpotifyPlaylistPage,
            page_processor=self._extract_playlists,
            limit=limit,
            prefix_log="[Playlists]",
        )
        logger.info(f"Found {len(playlists)} playlists. Fetching tracks...")

        # Use a Semaphore to limit concurrent playlist fetching to avoid rate limits and overwhelming resources.
        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def _fetch_with_semaphore(playlist: SpotifyPlaylist) -> list[Track]:
            async with semaphore:
                return await self._fetch_playlist_tracks(playlist, limit)

        # Fetch in parallel all playlist's tracks with a semaphore.
        async with asyncio.TaskGroup() as tg:
            tasks = [tg.create_task(_fetch_with_semaphore(playlist)) for playlist in playlists]

        # Gather all tracks first.
        tracks = [track for task in tasks for track in task.result()]
        # Then remove duplicates due to multiple playlists with the same tracks.
        return list({track.provider_id: track for track in tracks}.values())

    # -------------------------------------------------------------------------
    # Core Logic
    # -------------------------------------------------------------------------

    async def _refresh_token(self) -> None:
        # Double-check locking pattern to be safe against concurrency
        if self._is_token_refreshed:
            return

        async with self._refresh_lock:
            # Check again inside lock
            if self._is_token_refreshed:
                return

            token_state = await self.spotify_client.refresh_access_token(self.user.spotify_token_state.refresh_token)

            if token_state.access_token != self.user.spotify_token_state.access_token:
                # Update the token state in DB.
                await self.spotify_account_repository.update(
                    user_id=self.user.id,
                    spotify_account_data=token_state.to_user_update(),
                )
                # Update also the token state in memory.
                if self.user.spotify_account:  # pragma: no branch
                    self.user.spotify_account.token_type = token_state.token_type
                    self.user.spotify_account.token_access = token_state.access_token
                    self.user.spotify_account.token_refresh = token_state.refresh_token
                    self.user.spotify_account.token_expires_at = token_state.expires_at

            self._is_token_refreshed = True

    async def _fetch_playlist_tracks(self, playlist: SpotifyPlaylist, limit: int) -> list[Track]:
        tracks: list[Track] = []

        try:
            tracks = await self._fetch_pages(
                endpoint=f"/playlists/{playlist.id}/items",
                page_model=SpotifyPlaylistTrackPage,
                page_processor=self._extract_playlist_tracks,
                params={
                    "fields": "total,limit,offset,items(item(id,name,href,popularity,artists(id,name)))",
                    "additional_types": "track",
                },
                limit=limit,
                prefix_log=f"[PlaylistTracks({playlist.name})]",
            )
        except SpotifyPageValidationError as e:
            # Some playlist pages can return invalid data, like missing ID's.
            # Indeed, it could happen when manually uploading custom tracks not known by Spotify.
            logger.error(f"Skip playlist {playlist.name.strip()} with error: {e}")

        return tracks

    async def _fetch_pages[SpotifyPageType: SpotifyPage, MusicItemType: BaseMusicItem | SpotifyPlaylist](
        self,
        endpoint: str,
        page_model: type[SpotifyPageType],
        page_processor: Callable[[SpotifyPageType, int], list[MusicItemType]],
        method: str = "GET",
        params: dict[str, Any] | None = None,
        offset: int = 0,
        limit: int = 50,
        prefix_log: str = "",
    ) -> list[MusicItemType]:
        items: list[MusicItemType] = []

        logger.info(f"{prefix_log} Start fetching endpoint: {endpoint}")
        while True:
            data = await self._execute_request(
                method=method,
                endpoint=endpoint,
                params={
                    "offset": offset,
                    "limit": limit,
                    **(params or {}),
                },
            )

            try:
                page = page_model.model_validate(data)
            except ValidationError as e:
                raise SpotifyPageValidationError(
                    f"{prefix_log} - Page validation error on {endpoint} (offset: {offset}): {e}"
                ) from e

            items += page_processor(page, offset)

            logger.info(f"{prefix_log} ... processed {offset + limit}/{page.total} ...")
            if len(items) >= page.total or len(page.items) < limit:
                break

            offset += limit

        return items

    async def _execute_request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self._is_token_refreshed:
            await self._refresh_token()

        response_data, _ = await self.spotify_client.make_user_api_call(
            method=method,
            endpoint=endpoint,
            token_state=self.user.spotify_token_state,
            params=params,
            json_data=json_data,
        )
        return response_data

    # -------------------------------------------------------------------------
    # Extractors
    # -------------------------------------------------------------------------

    def _extract_playlists(self, page: SpotifyPlaylistPage, *_: Any) -> list[SpotifyPlaylist]:
        return list(page.items)

    def _extract_top_artists(self, page: SpotifyTopArtistPage, offset: int) -> list[Artist]:
        return [self._map_top_artist(item, offset + i + 1) for i, item in enumerate(page.items)]

    def _extract_top_tracks(self, page: SpotifyTopTrackPage, offset: int) -> list[Track]:
        return [self._map_top_track(item, offset + i + 1) for i, item in enumerate(page.items)]

    def _extract_saved_tracks(self, page: SpotifySavedTrackPage, *_: Any) -> list[Track]:
        return [self._map_saved_track(item.track) for item in page.items]

    def _extract_playlist_tracks(self, page: SpotifyPlaylistTrackPage, *_: Any) -> list[Track]:
        return [self._map_track(item.item) for item in page.items if item.item]

    # -------------------------------------------------------------------------
    # Mappers (DTO)
    # -------------------------------------------------------------------------

    def _map_top_artist(self, item: SpotifyArtist, position: int) -> Artist:
        return Artist.model_validate(
            {
                **item.model_dump(exclude={"id"}),
                "provider_id": item.id,
                "user_id": self.user.id,
                "is_top": True,
                "top_position": position,
            }
        )

    def _map_top_track(self, item: SpotifyTrack, position: int) -> Track:
        return self._map_track(item, is_top=True, top_position=position)

    def _map_saved_track(self, item: SpotifyTrack) -> Track:
        return self._map_track(item, is_saved=True)

    def _map_track(self, item: SpotifyTrack, **extra_attributes: Any) -> Track:
        return Track.model_validate(
            {
                **item.model_dump(exclude={"id", "artists"}),
                "provider_id": item.id,
                "user_id": self.user.id,
                "artists": [
                    {
                        **artist.model_dump(exclude={"id"}),
                        "provider_id": artist.id,
                    }
                    for artist in item.artists
                ],
                **extra_attributes,
            }
        )
