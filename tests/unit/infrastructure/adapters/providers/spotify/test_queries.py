from museflow.infrastructure.adapters.providers.spotify.queries import SpotifySearchTrackQuery


class TestSpotifySearchTrackQuery:
    def test__field__track(self) -> None:
        q = SpotifySearchTrackQuery(track='test es"cape').get_query()
        assert 'track:"test es\\"cape"' in q

    def test__field__is_new(self) -> None:
        q = SpotifySearchTrackQuery(
            track="S.D.E",
            is_new=True,
        ).get_query()

        assert "tag:new" in q

    def test__field__is_underground(self) -> None:
        q = SpotifySearchTrackQuery(
            track="S.D.E",
            is_underground=True,
        ).get_query()

        assert "tag:hipster" in q

    def test__field__is_isrc(self) -> None:
        q = SpotifySearchTrackQuery(
            track="S.D.E",
            isrc="USRc17605174",
        ).get_query()

        assert "isrc:USRc17605174" in q

    def test__field__artists__single(self) -> None:
        q = SpotifySearchTrackQuery(
            track="Track",
            artists=['Artist "1"'],
        ).get_query()
        assert 'artist:"Artist \\"1\\""' in q
        assert "(" not in q

    def test__field__artists__multiple(self) -> None:
        q = SpotifySearchTrackQuery(
            track="Track",
            artists=["Artist 1", "Artist 2", "Artist 3"],
        ).get_query()
        assert '(artist:"Artist 1" OR artist:"Artist 2" OR artist:"Artist 3")' in q

    def test__field__genres__single(self) -> None:
        q = SpotifySearchTrackQuery(
            track="Track",
            genres=['rock n" roll'],
        ).get_query()
        assert 'genre:"rock n\\" roll"' in q
        assert "(" not in q

    def test__field__genres__multiple(self) -> None:
        q = SpotifySearchTrackQuery(
            track="Track",
            genres=["rap", "rock", "pop"],
        ).get_query()
        assert '(genre:"rap" OR genre:"rock" OR genre:"pop")' in q

    def test__full_query(self) -> None:
        q = SpotifySearchTrackQuery(
            track="My Track",
            artists=["Artist A", "Artist B"],
            genres=["rock"],
            is_new=True,
            is_underground=True,
            isrc="USRc17605174",
        ).get_query()

        expected_parts = [
            'track:"My Track"',
            '(artist:"Artist A" OR artist:"Artist B")',
            'genre:"rock"',
            "tag:new",
            "tag:hipster",
            "isrc:USRc17605174",
        ]
        assert q == " ".join(expected_parts)
