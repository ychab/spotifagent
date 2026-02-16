import logging
from collections.abc import Awaitable
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
from typing import Any

from spotifagent.application.services.spotify import SpotifySessionFactory
from spotifagent.application.services.spotify import TimeRange
from spotifagent.domain.entities.users import User
from spotifagent.domain.exceptions import SpotifyAccountNotFoundError
from spotifagent.domain.ports.repositories.music import ArtistRepositoryPort
from spotifagent.domain.ports.repositories.music import TrackRepositoryPort

logger = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class SyncReport:
    purge_artist: int = 0
    purge_track: int = 0

    artist_created: int = 0
    artist_updated: int = 0

    track_created: int = 0
    track_updated: int = 0

    errors: list[str] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0


@dataclass(frozen=True)
class SyncConfig:
    """
    A synchronization configuration object.

    :param purge: Whether to purge all
    :param purge_artist_top: Whether to purge top artists
    :param purge_track_top: Whether to purge top tracks
    :param purge_track_saved: Whether to purge saved tracks
    :param purge_track_playlist: Whether to purge playlist tracks
    :param sync: Whether to sync all
    :param sync_artist_top: Whether to sync top artists
    :param sync_track_top: Whether to sync top tracks
    :param sync_track_saved: Whether to sync saved tracks
    :param sync_track_playlist: Whether to sync playlist tracks
    :param page_limit: The number of items to fetch
    :param time_range: The time range to fetch for top artists/ top tracks
    :param batch_size: The number of items to bulk upsert in DB
    """

    purge: bool = False
    purge_artist_top: bool = False
    purge_track_top: bool = False
    purge_track_saved: bool = False
    purge_track_playlist: bool = False
    sync: bool = False
    sync_artist_top: bool = False
    sync_track_top: bool = False
    sync_track_saved: bool = False
    sync_track_playlist: bool = False
    page_limit: int = 50
    time_range: TimeRange = "long_term"
    batch_size: int = 300

    def has_purge(self) -> bool:
        return any(
            [
                self.purge,
                self.purge_artist_top,
                self.purge_track_top,
                self.purge_track_saved,
                self.purge_track_playlist,
            ],
        )

    def has_sync(self) -> bool:
        return any(
            [
                self.sync,
                self.sync_artist_top,
                self.sync_track_top,
                self.sync_track_saved,
                self.sync_track_playlist,
            ]
        )


async def spotify_sync(
    user: User,
    spotify_session_factory: SpotifySessionFactory,
    artist_repository: ArtistRepositoryPort,
    track_repository: TrackRepositoryPort,
    config: SyncConfig,
) -> SyncReport:
    """
    For a given user, synchronize its Spotify items, including artists
    and tracks, depending on the given flags.

    :param user: A user object
    :param spotify_session_factory: Spotify session factory
    :param artist_repository: Artists repository
    :param track_repository: Tracks repository
    :param config: A configuration dataclass object

    :return: SyncReport
    """
    report = SyncReport()

    # First of all, purge items if required.
    if config.has_purge():
        if config.purge or config.purge_artist_top:
            report = await _purge(
                report=report,
                report_field_purge="purge_artist",
                user=user,
                entity_name="artists",
                purge_callback=lambda: artist_repository.purge(user_id=user.id),
            )

        if config.purge or config.purge_track_top or config.purge_track_saved or config.purge_track_playlist:
            report = await _purge(
                report=report,
                report_field_purge="purge_track",
                user=user,
                entity_name="tracks",
                purge_callback=lambda: track_repository.purge(
                    user_id=user.id,
                    is_top=config.purge_track_top and not config.purge,
                    is_saved=config.purge_track_saved and not config.purge,
                    is_playlist=config.purge_track_playlist and not config.purge,
                ),
            )

        if report.has_errors:
            return report

    # Then init a spotify user session (in case we just want to purge).
    try:
        spotify_session = spotify_session_factory.create(user)
    except SpotifyAccountNotFoundError:
        logger.debug(f"Spotify account not found for user {user.email}")
        return replace(report, errors=["You must connect your Spotify account first."])

    # Then fetch and upsert top artists.
    if config.sync or config.sync_artist_top:
        report = await _sync(
            report=report,
            report_field_created="artist_created",
            report_field_updated="artist_updated",
            user=user,
            entity_name="top artists",
            fetch_func=lambda: spotify_session.get_top_artists(
                limit=config.page_limit,
                time_range=config.time_range,
            ),
            upsert_func=lambda items: artist_repository.bulk_upsert(
                artists=items,
                batch_size=config.batch_size,
            ),
        )

    # Then fetch and upsert top tracks.
    if config.sync or config.sync_track_top:
        report = await _sync(
            report=report,
            report_field_created="track_created",
            report_field_updated="track_updated",
            user=user,
            entity_name="top tracks",
            fetch_func=lambda: spotify_session.get_top_tracks(
                limit=config.page_limit,
                time_range=config.time_range,
            ),
            upsert_func=lambda items: track_repository.bulk_upsert(
                tracks=items,
                batch_size=config.batch_size,
            ),
        )

    # Then fetch and upsert saved tracks.
    if config.sync or config.sync_track_saved:
        report = await _sync(
            report=report,
            report_field_created="track_created",
            report_field_updated="track_updated",
            user=user,
            entity_name="saved tracks",
            fetch_func=lambda: spotify_session.get_saved_tracks(
                limit=config.page_limit,
            ),
            upsert_func=lambda items: track_repository.bulk_upsert(
                tracks=items,
                batch_size=config.batch_size,
            ),
        )

    # Then fetch and upsert playlist tracks.
    if config.sync or config.sync_track_playlist:
        report = await _sync(
            report=report,
            report_field_created="track_created",
            report_field_updated="track_updated",
            user=user,
            entity_name="playlist tracks",
            fetch_func=lambda: spotify_session.get_playlist_tracks(
                limit=config.page_limit,
            ),
            upsert_func=lambda items: track_repository.bulk_upsert(
                tracks=items,
                batch_size=config.batch_size,
            ),
        )

    return report


async def _purge(
    report: SyncReport,
    report_field_purge: str,
    user: User,
    entity_name: str,
    purge_callback: Callable[[], Awaitable[int]],
) -> SyncReport:
    logger.info(f"About purging {entity_name} for user {user.email}...")

    try:
        count = await purge_callback()
    except Exception:
        logger.exception(f"An error occurred while purging {entity_name} for user {user.email}")
        report = replace(report, errors=report.errors + [f"An error occurred while purging your {entity_name}."])
    else:
        logger.info(f"Successfully purged {count} {entity_name} for user {user.email}")
        report_updates: dict[str, Any] = {report_field_purge: count}
        report = replace(report, **report_updates)

    return report


async def _sync[T](
    report: SyncReport,
    report_field_created: str,
    report_field_updated: str,
    user: User,
    entity_name: str,
    fetch_func: Callable[[], Awaitable[list[T]]],
    upsert_func: Callable[[list[T]], Awaitable[tuple[list[Any], int]]],
) -> SyncReport:
    logger.info(f"About synchronizing {entity_name} for user {user.email}...")

    # Fetch step
    try:
        items = await fetch_func()
    except Exception:
        logger.exception(f"An error occurred while fetching {entity_name} for user {user.email}")
        report = replace(report, errors=report.errors + [f"An error occurred while fetching Spotify {entity_name}."])
        return report
    else:
        logger.info(f"Fetched {len(items)} {entity_name} for user {user.email}")

    # Upsert step
    try:
        ids, created = await upsert_func(items)
    except Exception:
        logger.exception(f"An error occurred while upserting {entity_name} for user {user.email}")
        report = replace(report, errors=report.errors + [f"An error occurred while saving Spotify {entity_name}."])
        return report
    else:
        logger.info(f"Upserted {len(ids)} {entity_name} for user {user.email}")

    report_updates: dict[str, Any] = {
        report_field_created: getattr(report, report_field_created) + created,
        report_field_updated: getattr(report, report_field_updated) + (len(ids) - created),
    }
    return replace(report, **report_updates)
