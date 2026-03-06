import json
import logging
from typing import Any

import pytest

from museflow.domain.entities.music import Track
from museflow.domain.exceptions import ProviderPageValidationError
from museflow.domain.types import MusicProvider
from museflow.infrastructure.adapters.providers.spotify.library import SpotifyLibraryAdapter

from tests import ASSETS_DIR
from tests.integration.factories.models.music import TrackModelFactory
from tests.integration.utils.wiremock import WireMockContext


class TestSpotifyLibrary:
    @pytest.fixture
    def track_locale(self) -> dict[str, Any]:
        return {
            "id": None,
            "name": "local-file",
            "href": None,
            "popularity": 0,
            "is_local": True,
            "artists": [
                {
                    "id": None,
                    "name": "",
                },
            ],
        }

    @pytest.fixture
    def wiremock_response(self, request: pytest.FixtureRequest) -> dict[str, Any]:
        filename = getattr(request, "param", "")
        filepath = ASSETS_DIR / "wiremock" / "spotify" / "__files" / f"{filename}.json"
        return json.loads(filepath.read_text())

    @pytest.fixture
    async def playlist_tracks(self) -> list[Track]:
        return [
            (await TrackModelFactory.create_async(provider_id=track_id)).to_entity()
            for track_id in ["7J5pB49l9ycy9ImB6D9hu0", "1Fp4njyRHJYyMTKP899c0q", "7eOSOc9z6gcsGBznsg5mk3"]
        ]

    async def test__get_top_artists__nominal(self, spotify_library: SpotifyLibraryAdapter) -> None:
        page_size = 5

        top_artists = await spotify_library.get_top_artists(page_size=page_size)
        assert len(top_artists) == 15

        top_artist_first = top_artists[0]
        assert top_artist_first.id is not None
        assert top_artist_first.user_id == spotify_library.user.id
        assert top_artist_first.name == "Vald"
        assert top_artist_first.popularity == 64
        assert top_artist_first.is_saved is False
        assert top_artist_first.is_top is True
        assert top_artist_first.top_position == 1
        assert top_artist_first.genres == ["rap français"]
        assert top_artist_first.provider == MusicProvider.SPOTIFY
        assert top_artist_first.provider_id == "3CnCGFxXbOA8bAK54jR8js"

        top_artist_last = top_artists[-1]
        assert top_artist_last.id is not None
        assert top_artist_last.user_id == spotify_library.user.id
        assert top_artist_last.name == "Grupo Niche"
        assert top_artist_last.popularity == 69
        assert top_artist_last.is_saved is False
        assert top_artist_last.is_top is True
        assert top_artist_last.top_position == len(top_artists) == 15
        assert top_artist_last.genres == ["salsa", "merengue"]
        assert top_artist_last.provider == MusicProvider.SPOTIFY
        assert top_artist_last.provider_id == "1zng9JZpblpk48IPceRWs8"

    async def test__get_top_artists__max_pages(self, spotify_library: SpotifyLibraryAdapter) -> None:
        page_size = 5
        max_pages = 1

        top_artists = await spotify_library.get_top_artists(page_size=page_size, max_pages=max_pages)
        assert len(top_artists) == page_size * max_pages

    async def test__get_top_tracks__nominal(self, spotify_library: SpotifyLibraryAdapter) -> None:
        page_size = 5

        top_tracks = await spotify_library.get_top_tracks(page_size=page_size)
        assert len(top_tracks) == 15

        top_track_first = top_tracks[0]
        assert top_track_first.id is not None
        assert top_track_first.user_id == spotify_library.user.id
        assert top_track_first.name == "La Negra No Quiere"
        assert top_track_first.popularity == 19
        assert top_track_first.is_saved is False
        assert top_track_first.is_top is True
        assert top_track_first.top_position == 1
        assert len(top_track_first.artists) == 1
        assert top_track_first.artists[0].provider_id == "1zng9JZpblpk48IPceRWs8"
        assert top_track_first.artists[0].name == "Grupo Niche"
        assert top_track_first.provider == MusicProvider.SPOTIFY
        assert top_track_first.provider_id == "7J5pB49l9ycy9ImB6D9hu0"

        top_track_last = top_tracks[-1]
        assert top_track_last.id is not None
        assert top_track_last.user_id == spotify_library.user.id
        assert top_track_last.name == "Ché Ché Colé"
        assert top_track_last.popularity == 63
        assert top_track_last.is_saved is False
        assert top_track_last.is_top is True
        assert top_track_last.top_position == len(top_tracks) == 15
        assert len(top_track_last.artists) == 2
        assert top_track_last.artists[0].provider_id == "7x5Slu7yTE5icZjNsc3OzW"
        assert top_track_last.artists[0].name == "Willie Colón"
        assert top_track_last.artists[1].provider_id == "7opp16lU7VM3l2WBdGMYHP"
        assert top_track_last.artists[1].name == "Héctor Lavoe"
        assert top_track_last.provider == MusicProvider.SPOTIFY
        assert top_track_last.provider_id == "4rPtnAmfvHkVSCO2KKkiC1"

    async def test__get_top_tracks__max_pages(self, spotify_library: SpotifyLibraryAdapter) -> None:
        page_size = 5
        max_pages = 1

        top_tracks = await spotify_library.get_top_tracks(page_size=page_size, max_pages=max_pages)
        assert len(top_tracks) == page_size * max_pages

    @pytest.mark.parametrize("wiremock_response", ["top_tracks_page_1"], indirect=["wiremock_response"])
    async def test__get_top_tracks__local_files(
        self,
        spotify_library: SpotifyLibraryAdapter,
        track_locale: dict[str, Any],
        wiremock_response: dict[str, Any],
        spotify_wiremock: WireMockContext,
    ) -> None:
        page_size = 5

        wiremock_response["total"] = page_size
        wiremock_response["items"][0] = track_locale

        spotify_wiremock.create_mapping(
            method="GET",
            url_path="/me/top/tracks",
            status=200,
            query_params={
                "offset": 0,
                "limit": page_size,
            },
            json_body=wiremock_response,
        )

        with pytest.raises(ProviderPageValidationError, match="Unsupported local files") as exc_info:
            await spotify_library.get_top_tracks(page_size=page_size)
        assert exc_info.value.code == "unsupported_local_files"

    async def test__get_saved_tracks__nominal(self, spotify_library: SpotifyLibraryAdapter) -> None:
        page_size = 5

        tracks_saved = await spotify_library.get_saved_tracks(page_size=page_size)
        assert len(tracks_saved) == 15

        track_saved_first = tracks_saved[0]
        assert track_saved_first.id is not None
        assert track_saved_first.user_id == spotify_library.user.id
        assert track_saved_first.name == "Un Zder, Un Thé"
        assert track_saved_first.popularity == 56
        assert track_saved_first.is_saved is True
        assert track_saved_first.is_top is False
        assert track_saved_first.top_position is None
        assert len(track_saved_first.artists) == 1
        assert track_saved_first.artists[0].provider_id == "6dbdXbyAWk2qx8Qttw0knR"
        assert track_saved_first.artists[0].name == "Josman"
        assert track_saved_first.provider == MusicProvider.SPOTIFY
        assert track_saved_first.provider_id == "3GsmreScQWMqOyuyW1Dac2"

        track_saved_last = tracks_saved[-1]
        assert track_saved_last.id is not None
        assert track_saved_last.user_id == spotify_library.user.id
        assert track_saved_last.name == "La zone"
        assert track_saved_last.popularity == 43
        assert track_saved_last.is_saved is True
        assert track_saved_last.is_top is False
        assert track_saved_last.top_position is None
        assert len(track_saved_last.artists) == 2
        assert track_saved_last.artists[0].provider_id == "0LKAV3zJ8a8AIGnyc5OvfB"
        assert track_saved_last.artists[0].name == "SDM"
        assert track_saved_last.artists[1].provider_id == "58wXmynHaAWI5hwlPZP3qL"
        assert track_saved_last.artists[1].name == "Booba"
        assert track_saved_last.provider == MusicProvider.SPOTIFY
        assert track_saved_last.provider_id == "6Y8i5zcz6wTi11HN88iNLW"

    async def test__get_saved_tracks__max_pages(self, spotify_library: SpotifyLibraryAdapter) -> None:
        page_size = 5
        max_pages = 1

        tracks_saved = await spotify_library.get_saved_tracks(page_size=page_size, max_pages=max_pages)
        assert len(tracks_saved) == page_size * max_pages

    @pytest.mark.parametrize("wiremock_response", ["saved_tracks_page_1"], indirect=["wiremock_response"])
    async def test__get_saved_tracks__local_files(
        self,
        spotify_library: SpotifyLibraryAdapter,
        track_locale: dict[str, Any],
        wiremock_response: dict[str, Any],
        spotify_wiremock: WireMockContext,
    ) -> None:
        page_size = 5

        wiremock_response["total"] = page_size
        wiremock_response["items"][0]["track"] = track_locale

        spotify_wiremock.create_mapping(
            method="GET",
            url_path="/me/tracks",
            status=200,
            query_params={
                "offset": 0,
                "limit": page_size,
            },
            json_body=wiremock_response,
        )

        with pytest.raises(ProviderPageValidationError, match="Unsupported local files") as exc_info:
            await spotify_library.get_saved_tracks(page_size=page_size)
        assert exc_info.value.code == "unsupported_local_files"

    async def test__get_playlist_tracks__nominal(self, spotify_library: SpotifyLibraryAdapter) -> None:
        page_size = 1
        playlist_total = 2 * page_size
        playlist_tracks_total = 2 * page_size

        tracks = await spotify_library.get_playlist_tracks(page_size=page_size)
        assert len(tracks) == playlist_total * playlist_tracks_total

        track_first = tracks[0]
        assert track_first.id is not None
        assert track_first.user_id == spotify_library.user.id
        assert track_first.name == "Rolls (feat. Lacrim)"
        assert track_first.popularity == 44
        assert track_first.is_saved is False
        assert track_first.is_top is False
        assert track_first.top_position is None
        assert len(track_first.artists) == 2
        assert track_first.artists[0].provider_id == "1kwzW1IszUiq4Gs9BFesvW"
        assert track_first.artists[0].name == "Hornet La Frappe"
        assert track_first.artists[1].provider_id == "7DUTsWY3RBd64vh8UtgtYA"
        assert track_first.artists[1].name == "Lacrim"
        assert track_first.provider == MusicProvider.SPOTIFY
        assert track_first.provider_id == "3iYv5nIthPXesF0DeuhmVL"

        track_last = tracks[-1]
        assert track_last.id is not None
        assert track_last.user_id == spotify_library.user.id
        assert track_last.name == "Yo Te Canto"
        assert track_last.popularity == 2
        assert track_last.is_saved is False
        assert track_last.is_top is False
        assert track_last.top_position is None
        assert len(track_last.artists) == 1
        assert track_last.artists[0].provider_id == "6DGyKmbV7zJrnjlNmpA0j9"
        assert track_last.artists[0].name == "Piper Pimienta"
        assert track_last.provider == MusicProvider.SPOTIFY
        assert track_last.provider_id == "7CmDeBNvuklb5WvErkDkTj"

    async def test__get_playlist_tracks__max_pages(self, spotify_library: SpotifyLibraryAdapter) -> None:
        page_size = 1
        max_pages = 1

        playlist_total = page_size * max_pages
        playlist_tracks_total = page_size * max_pages

        tracks = await spotify_library.get_playlist_tracks(page_size=page_size, max_pages=max_pages)
        assert len(tracks) == playlist_total * playlist_tracks_total

    @pytest.mark.parametrize(
        "wiremock_response", ["playlist_items_0wKgiV47itigJyxBgFxAu1_page_1"], indirect=["wiremock_response"]
    )
    async def test__get_playlist_tracks__duplicates(
        self,
        spotify_library: SpotifyLibraryAdapter,
        wiremock_response: dict[str, Any],
        spotify_wiremock: WireMockContext,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        page_size = 1

        track_duplicate = wiremock_response["items"][0]["item"]
        for i in range(len(wiremock_response["items"])):
            wiremock_response["items"][i]["item"] = track_duplicate

        for offset in range(0, 2, page_size):
            spotify_wiremock.create_mapping(
                method="GET",
                url_path="/playlists/0wKgiV47itigJyxBgFxAu1/items",
                status=200,
                query_params={
                    "offset": offset,
                    "limit": page_size,
                    "fields": "total,limit,offset,items(item(id,name,href,popularity,is_local,artists(id,name)))",
                    "additional_types": "track",
                },
                json_body=wiremock_response,
            )
            spotify_wiremock.create_mapping(
                method="GET",
                url_path="/playlists/1xnKqEZDpMWvrts4M9I9GC/items",
                status=200,
                query_params={
                    "offset": offset,
                    "limit": page_size,
                    "fields": "total,limit,offset,items(item(id,name,href,popularity,is_local,artists(id,name)))",
                    "additional_types": "track",
                },
                json_body=wiremock_response,
            )

        tracks = await spotify_library.get_playlist_tracks(page_size=page_size)
        assert len(tracks) == 1

    @pytest.mark.parametrize(
        "wiremock_response", ["playlist_items_0wKgiV47itigJyxBgFxAu1_page_1"], indirect=["wiremock_response"]
    )
    async def test__get_playlist_tracks__local_files(
        self,
        spotify_library: SpotifyLibraryAdapter,
        track_locale: dict[str, Any],
        wiremock_response: dict[str, Any],
        spotify_wiremock: WireMockContext,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        page_size = 1

        wiremock_response["total"] = page_size
        wiremock_response["items"][0]["item"] = track_locale

        spotify_wiremock.create_mapping(
            method="GET",
            url_path="/playlists/0wKgiV47itigJyxBgFxAu1/items",
            status=200,
            query_params={
                "offset": 0,
                "limit": page_size,
                "fields": "total,limit,offset,items(item(id,name,href,popularity,is_local,artists(id,name)))",
                "additional_types": "track",
            },
            json_body=wiremock_response,
        )

        with caplog.at_level(logging.ERROR):
            await spotify_library.get_playlist_tracks(page_size=page_size)

        assert "Skip playlist Salsa with error" in caplog.text
        assert "Unsupported local files" in caplog.text

    async def test__search__nominal(
        self,
        playlist_tracks: list[Track],
        spotify_library: SpotifyLibraryAdapter,
    ) -> None:
        tracks = await spotify_library.search_tracks(track="bedstories", page_size=5)
        assert len(tracks) == 15

        track_first = tracks[0]
        assert track_first.id is not None
        assert track_first.user_id == spotify_library.user.id
        assert track_first.name == "Bedtime Stories (feat. The Weeknd) - From SR3MM"
        assert track_first.popularity == 50
        assert track_first.is_saved is False
        assert track_first.is_top is False
        assert track_first.top_position is None
        assert len(track_first.artists) == 4
        assert track_first.artists[0].provider_id == "7iZtZyCzp3LItcw1wtPI3D"
        assert track_first.artists[0].name == "Rae Sremmurd"
        assert track_first.artists[1].provider_id == "1zNqQNIdeOUZHb8zbZRFMX"
        assert track_first.artists[1].name == "Swae Lee"
        assert track_first.artists[2].provider_id == "7EEiVZvj6RCEtVX2F2pyxu"
        assert track_first.artists[2].name == "Slim Jxmmi"
        assert track_first.artists[3].provider_id == "1Xyo4u8uXC1ZmMpatF05PJ"
        assert track_first.artists[3].name == "The Weeknd"
        assert track_first.provider == MusicProvider.SPOTIFY
        assert track_first.provider_id == "6nI74KsH94IN0J2vp5shdT"

        track_last = tracks[-1]
        assert track_last.id is not None
        assert track_last.user_id == spotify_library.user.id
        assert track_last.name == "Secret"
        assert track_last.popularity == 59
        assert track_last.is_saved is False
        assert track_last.is_top is False
        assert track_last.top_position is None
        assert len(track_last.artists) == 1
        assert track_last.artists[0].provider_id == "6tbjWDEIzxoDsBA1FuhfPW"
        assert track_last.artists[0].name == "Madonna"
        assert track_last.provider == MusicProvider.SPOTIFY
        assert track_last.provider_id == "15FcP9qwmIKqaD5NhfhNpu"

    async def test__create_playlist__nominal(
        self,
        playlist_tracks: list[Track],
        spotify_library: SpotifyLibraryAdapter,
    ) -> None:
        playlist = await spotify_library.create_playlist(name="test", tracks=playlist_tracks)

        assert playlist.id is not None
        assert playlist.user_id == spotify_library.user.id
        assert playlist.name == "test"
        assert playlist.slug == "test"
        assert playlist.provider == MusicProvider.SPOTIFY
        assert playlist.provider_id == "5ta70oLZcXLReU7bEEXQXy"
        assert playlist.snapshot_id == "AAAAAsNYTkn8k2rpWWck/VOdy+GiqV1c"
        assert playlist.tracks == playlist_tracks
