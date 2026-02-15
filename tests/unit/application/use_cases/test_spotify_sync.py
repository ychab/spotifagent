import logging
from unittest import mock

from httpx import HTTPError

from pydantic import BaseModel
from pydantic import ValidationError
from pydantic import model_validator

from sqlalchemy.exc import SQLAlchemyError

import pytest

from spotifagent.application.services.spotify import SpotifySessionFactory
from spotifagent.application.services.spotify import SpotifyUserSession
from spotifagent.application.use_cases.spotify_sync import SyncReport
from spotifagent.application.use_cases.spotify_sync import spotify_sync
from spotifagent.domain.entities.music import Artist
from spotifagent.domain.entities.music import Track
from spotifagent.domain.entities.users import User
from spotifagent.domain.exceptions import SpotifyAccountNotFoundError

from tests.unit.factories.music import ArtistFactory
from tests.unit.factories.music import TrackFactory
from tests.unit.factories.users import UserFactory


def validation_error() -> ValidationError:
    """
    Mimic a dummy Pydantic ValidationError with a KISS approach.

    Indeed, we tried to instance it manually but the signature is not obvious
    at all and may change in the future (whereas this dummy code shouldn't!).
    """

    class DummyModel(BaseModel):
        dummy_field: int

        @model_validator(mode="after")
        def blow_up(self):
            raise ValueError("Boom")

    with pytest.raises(ValidationError) as exc_info:
        DummyModel(dummy_field=50)

    return exc_info.value


class TestSpotifySync:
    @pytest.fixture
    def user(self) -> User:
        return UserFactory.build(with_spotify_account=True)

    @pytest.fixture
    def artists(self) -> list[Artist]:
        return ArtistFactory.batch(size=10)

    @pytest.fixture
    def tracks(self) -> list[Track]:
        return TrackFactory.batch(size=10)

    @pytest.fixture
    def mock_spotify_session(self, user: User, artists: list[Artist], tracks: list[Track]) -> mock.Mock:
        return mock.Mock(
            spec=SpotifyUserSession,
            user=user,
            get_top_artists=mock.AsyncMock(return_value=artists),
            get_top_tracks=mock.AsyncMock(return_value=tracks),
        )

    @pytest.fixture
    def mock_spotify_session_factory(self, mock_spotify_session: mock.Mock) -> mock.Mock:
        return mock.Mock(
            spec=SpotifySessionFactory,
            create=mock.Mock(return_value=mock_spotify_session),
        )

    async def test__do_nothing(
        self,
        user: User,
        mock_spotify_session_factory: mock.Mock,
        mock_artist_repository: mock.AsyncMock,
        mock_track_repository: mock.AsyncMock,
    ) -> None:
        report = await spotify_sync(
            user=user,
            spotify_session_factory=mock_spotify_session_factory,
            artist_repository=mock_artist_repository,
            track_repository=mock_track_repository,
        )
        assert report == SyncReport()

    async def test__purge__artist__exception(
        self,
        user: User,
        mock_spotify_session_factory: mock.Mock,
        mock_artist_repository: mock.AsyncMock,
        mock_track_repository: mock.AsyncMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        mock_artist_repository.purge.side_effect = SQLAlchemyError("Boom")

        with caplog.at_level(logging.ERROR):
            report = await spotify_sync(
                user=user,
                spotify_session_factory=mock_spotify_session_factory,
                artist_repository=mock_artist_repository,
                track_repository=mock_track_repository,
                purge_artist_top=True,
            )

        assert report == SyncReport(errors=["An error occurred while purging your artists."])
        assert f"An error occurred while purging artists for user {user.email}" in caplog.text

    @pytest.mark.parametrize(("purge_track_top", "purge_track_saved"), [(True, True), (True, False), (False, True)])
    async def test__purge__track__exception(
        self,
        user: User,
        purge_track_top: bool,
        purge_track_saved: bool,
        mock_spotify_session_factory: mock.Mock,
        mock_artist_repository: mock.AsyncMock,
        mock_track_repository: mock.AsyncMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        mock_track_repository.purge.side_effect = SQLAlchemyError("Boom")

        with caplog.at_level(logging.ERROR):
            report = await spotify_sync(
                user=user,
                spotify_session_factory=mock_spotify_session_factory,
                artist_repository=mock_artist_repository,
                track_repository=mock_track_repository,
                purge_track_top=purge_track_top,
                purge_track_saved=purge_track_saved,
            )

        assert report == SyncReport(errors=["An error occurred while purging your tracks."])
        assert f"An error occurred while purging tracks for user {user.email}" in caplog.text

    async def test__user__spotify_account_not_found(
        self,
        user: User,
        mock_spotify_session_factory: mock.Mock,
        mock_artist_repository: mock.AsyncMock,
        mock_track_repository: mock.AsyncMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        mock_spotify_session_factory.create.side_effect = SpotifyAccountNotFoundError("Boom")

        with caplog.at_level(logging.DEBUG):
            report = await spotify_sync(
                user=user,
                spotify_session_factory=mock_spotify_session_factory,
                artist_repository=mock_artist_repository,
                track_repository=mock_track_repository,
            )

        assert report == SyncReport(errors=["You must connect your Spotify account first."])
        assert f"Spotify account not found for user {user.email}" in caplog.text

    @pytest.mark.parametrize("exception_raised", [HTTPError("Boom"), validation_error()])
    async def test__artist__fetch__exception(
        self,
        user: User,
        mock_spotify_session_factory: mock.Mock,
        mock_spotify_session: mock.Mock,
        mock_artist_repository: mock.AsyncMock,
        mock_track_repository: mock.AsyncMock,
        exception_raised: Exception,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        mock_spotify_session.get_top_artists.side_effect = exception_raised

        with caplog.at_level(logging.ERROR):
            report = await spotify_sync(
                user=user,
                spotify_session_factory=mock_spotify_session_factory,
                artist_repository=mock_artist_repository,
                track_repository=mock_track_repository,
                sync_artist_top=True,
            )

        assert report == SyncReport(errors=["An error occurred while fetching Spotify artists."])
        assert f"An error occurred while fetching artists for user {user.email}" in caplog.text

    @pytest.mark.parametrize("exception_raised", [SQLAlchemyError("Boom"), validation_error()])
    async def test__artist__bulk_upsert__exception(
        self,
        user: User,
        mock_spotify_session_factory: mock.Mock,
        mock_spotify_session: mock.Mock,
        mock_artist_repository: mock.AsyncMock,
        mock_track_repository: mock.AsyncMock,
        exception_raised: Exception,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        mock_artist_repository.bulk_upsert.side_effect = exception_raised

        with caplog.at_level(logging.ERROR):
            report = await spotify_sync(
                user=user,
                spotify_session_factory=mock_spotify_session_factory,
                artist_repository=mock_artist_repository,
                track_repository=mock_track_repository,
                sync_artist_top=True,
            )

        assert report == SyncReport(errors=["An error occurred while saving Spotify artists."])
        assert f"An error occurred while upserting artists for user {user.email}" in caplog.text

    @pytest.mark.parametrize("exception_raised", [HTTPError("Boom"), validation_error()])
    async def test__track_top__fetch__exception(
        self,
        user: User,
        mock_spotify_session_factory: mock.Mock,
        mock_spotify_session: mock.Mock,
        mock_artist_repository: mock.AsyncMock,
        mock_track_repository: mock.AsyncMock,
        exception_raised: Exception,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        mock_spotify_session.get_top_tracks.side_effect = exception_raised

        with caplog.at_level(logging.ERROR):
            report = await spotify_sync(
                user=user,
                spotify_session_factory=mock_spotify_session_factory,
                artist_repository=mock_artist_repository,
                track_repository=mock_track_repository,
                sync_track_top=True,
            )

        assert report == SyncReport(errors=["An error occurred while fetching Spotify top tracks."])
        assert f"An error occurred while fetching top tracks for user {user.email}" in caplog.text

    @pytest.mark.parametrize("exception_raised", [SQLAlchemyError("Boom"), validation_error()])
    async def test__track_top__bulk_upsert__exception(
        self,
        user: User,
        mock_spotify_session_factory: mock.Mock,
        mock_spotify_session: mock.Mock,
        mock_artist_repository: mock.AsyncMock,
        mock_track_repository: mock.AsyncMock,
        exception_raised: Exception,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        mock_track_repository.bulk_upsert.side_effect = exception_raised

        with caplog.at_level(logging.ERROR):
            report = await spotify_sync(
                user=user,
                spotify_session_factory=mock_spotify_session_factory,
                artist_repository=mock_artist_repository,
                track_repository=mock_track_repository,
                sync_track_top=True,
            )

        assert report == SyncReport(errors=["An error occurred while saving Spotify top tracks."])
        assert f"An error occurred while upserting top tracks for user {user.email}" in caplog.text

    @pytest.mark.parametrize("exception_raised", [HTTPError("Boom"), validation_error()])
    async def test__track_saved__fetch__exception(
        self,
        user: User,
        mock_spotify_session_factory: mock.Mock,
        mock_spotify_session: mock.Mock,
        mock_artist_repository: mock.AsyncMock,
        mock_track_repository: mock.AsyncMock,
        exception_raised: Exception,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        mock_spotify_session.get_saved_tracks.side_effect = exception_raised

        with caplog.at_level(logging.ERROR):
            report = await spotify_sync(
                user=user,
                spotify_session_factory=mock_spotify_session_factory,
                artist_repository=mock_artist_repository,
                track_repository=mock_track_repository,
                sync_track_saved=True,
            )

        assert report == SyncReport(errors=["An error occurred while fetching Spotify saved tracks."])
        assert f"An error occurred while fetching saved tracks for user {user.email}" in caplog.text

    @pytest.mark.parametrize("exception_raised", [SQLAlchemyError("Boom"), validation_error()])
    async def test__track_saved__bulk_upsert__exception(
        self,
        user: User,
        mock_spotify_session_factory: mock.Mock,
        mock_spotify_session: mock.Mock,
        mock_artist_repository: mock.AsyncMock,
        mock_track_repository: mock.AsyncMock,
        exception_raised: Exception,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        mock_track_repository.bulk_upsert.side_effect = exception_raised

        with caplog.at_level(logging.ERROR):
            report = await spotify_sync(
                user=user,
                spotify_session_factory=mock_spotify_session_factory,
                artist_repository=mock_artist_repository,
                track_repository=mock_track_repository,
                sync_track_saved=True,
            )

        assert report == SyncReport(errors=["An error occurred while saving Spotify saved tracks."])
        assert f"An error occurred while upserting saved tracks for user {user.email}" in caplog.text
