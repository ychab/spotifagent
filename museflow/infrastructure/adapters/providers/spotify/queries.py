from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field


class SpotifySearchTrackQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    track: str = Field(min_length=1)
    artists: list[str] = Field(default_factory=list)
    genres: list[str] = Field(default_factory=list)
    is_new: bool = False
    is_underground: bool = False
    isrc: str | None = None

    def _escape(self, val: str) -> str:
        return val.replace('"', '\\"')

    def _build_multiple_params(self, key: str, values: list[str]) -> str | None:
        if not values:
            return None

        query = " OR ".join([f'{key}:"{self._escape(v)}"' for v in values])

        # Spotify bug if a single value has parenthesis but are required for multiple values.
        return f"({query})" if len(values) > 1 else query

    def get_query(self) -> str:
        parts = [f'track:"{self._escape(self.track)}"']

        if artist_part := self._build_multiple_params("artist", self.artists):
            parts.append(artist_part)

        if genre_part := self._build_multiple_params("genre", self.genres):
            parts.append(genre_part)

        if self.is_new:
            parts.append("tag:new")

        if self.is_underground:
            parts.append("tag:hipster")

        if self.isrc:
            parts.append(f"isrc:{self.isrc}")

        return " ".join(parts)
