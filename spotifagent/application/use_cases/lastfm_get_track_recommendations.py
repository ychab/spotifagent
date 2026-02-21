import asyncio
from contextlib import AsyncExitStack

from spotifagent.infrastructure.entrypoints.cli.dependencies import (
    get_track_repository, get_db,
    get_user_repository, get_lastfm_client,
)


async def main():
    async with AsyncExitStack() as stack:
        session = await stack.enter_async_context(get_db())

        user_repository = get_user_repository(session)
        track_repository = get_track_repository(session)
        lastfm_client = await stack.enter_async_context(get_lastfm_client())

        user = await user_repository.get_by_email("yannick.chabbert@gmail.com")
        if not user:
            return

        # order randomly? include top only? include saved only?
        tracks = await track_repository.get_list(user.id, limit=50)

        results = []
        for track in tracks:
            result = await lastfm_client.get_similar_tracks(
                artist_name=", ".join([a.name for a in track.artists]),
                track_name=track.name,
            )
            if result:
                results.append(result)

        print(results)


if __name__ == "__main__":
    asyncio.run(main())
