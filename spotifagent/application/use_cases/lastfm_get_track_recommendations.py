import asyncio
from contextlib import AsyncExitStack

import httpx
import os

from spotifagent.infrastructure.entrypoints.cli.dependencies import get_top_track_repository, get_db, \
    get_user_repository, get_top_artist_repository


async def get_similar_tracks(artist_name: str, track_name: str, api_key: str, limit: int = 5):
    """
    Asynchronously fetches tracks similar to the given artist and track from Last.fm.
    """
    url = "http://ws.audioscrobbler.com/2.0/"

    params = {
        'method': 'track.getSimilar',
        'artist': artist_name,
        'track': track_name,
        'api_key': api_key,
        'format': 'json',
        'limit': limit,
        'autocorrect': 1
    }

    # Use AsyncClient for asynchronous requests
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, params=params)
            response.raise_for_status()  # Raises httpx.HTTPStatusError for 4xx/5xx responses

            data = response.json()

            # Parsing logic remains the same
            if 'similartracks' in data and 'track' in data['similartracks']:
                tracks = data['similartracks']['track']

                if not tracks:
                    print(f"No similar tracks found for {track_name} by {artist_name}.")
                    return

                print(f"--- Recommendations based on '{track_name}' by {artist_name} ---")
                for idx, item in enumerate(tracks, 1):
                    name = item.get('name', 'Unknown Track')
                    artist = item.get('artist', {}).get('name', 'Unknown Artist')
                    # Last.fm returns match as a float between 0 and 1
                    match_score = float(item.get('match', 0)) * 100
                    url = item.get('url', '#')

                    print(f"{idx}. {name} - {artist}")
                    print(f"   Match: {match_score:.1f}% | Link: {url}")
                    return {"name": name, "artist": artist, "match": match_score, "url": url}
            else:
                print("Error: Unexpected API response structure.")

        except httpx.HTTPStatusError as exc:
            print(f"HTTP Error {exc.response.status_code} while requesting {exc.request.url!r}.")
        except httpx.RequestError as exc:
            print(f"An error occurred while requesting {exc.request.url!r}: {exc}")
        except Exception as exc:
            print(f"Unexpected error: {exc}")


async def main():
    # REPLACE THIS with your actual Last.fm API Key
    API_KEY = os.getenv("LASTFM_CLIENT_API_KEY")

    # artist_tracks = [
    #     ("Vald", "Blauwburgwal"),
    #     ("Vald", "Ce monde est cruel"),
    #     ("Orelsan", "Ailleurs"),
    #     ("Damso", "Magic"),
    # ]

    async with AsyncExitStack() as stack:
        session = await stack.enter_async_context(get_db())

        user_repository = get_user_repository(session)
        top_artist_repository = get_top_artist_repository(session)
        top_track_repository = get_top_track_repository(session)

        user = await user_repository.get_by_email("yannick.chabbert@gmail.com")
        if not user:
            return

        top_tracks = await top_track_repository.get_list(user.id)

        results = []
        for top_track in top_tracks[-50:]:
            result = await get_similar_tracks(", ".join([a.name for a in top_track.artists]), top_track.name, API_KEY)
            if result:
                results.append(result)

        print(results)


if __name__ == "__main__":
    asyncio.run(main())
