import asyncio
import time
from contextlib import AsyncExitStack

from pydantic import EmailStr

from sqlalchemy.ext.asyncio import AsyncSession

import typer

from spotifagent.application.use_cases.spotify_oauth_redirect import spotify_oauth_redirect
from spotifagent.domain.exceptions import UserNotFound
from spotifagent.domain.ports.repositories.users import UserRepositoryPort
from spotifagent.infrastructure.entrypoints.cli.dependencies import get_db
from spotifagent.infrastructure.entrypoints.cli.dependencies import get_spotify_client
from spotifagent.infrastructure.entrypoints.cli.dependencies import get_state_token_generator
from spotifagent.infrastructure.entrypoints.cli.dependencies import get_user_repository


async def connect_logic(email: EmailStr, timeout: float, poll_interval: float) -> None:
    async with AsyncExitStack() as stack:
        session = await stack.enter_async_context(get_db())
        spotify_client = await stack.enter_async_context(get_spotify_client())
        user_repository = get_user_repository(session)
        state_token_generator = get_state_token_generator()

        user = await user_repository.get_by_email(email)
        if not user:
            raise UserNotFound()

        authorization_url = await spotify_oauth_redirect(
            user=user,
            user_repository=user_repository,
            spotify_client=spotify_client,
            state_token_generator=state_token_generator,
        )

        # Then launch a browser.
        typer.echo(f"Opening browser for authentication: {authorization_url}")
        typer.launch(str(authorization_url))

        await _wait_for_authentication(
            session=session,
            user_repository=user_repository,
            email=email,
            timeout=timeout,
            poll_interval=poll_interval,
        )


async def _wait_for_authentication(
    session: AsyncSession,
    user_repository: UserRepositoryPort,
    email: EmailStr,
    timeout: float,
    poll_interval: float,
) -> None:
    typer.echo("Waiting for authentication completion", nl=False)
    start_time = time.time()

    while time.time() - start_time < timeout:
        await asyncio.sleep(poll_interval)
        typer.echo(".", nl=False)  # Visual feedback

        # Force SQLAlchemy to forget cached data so we see external updates
        session.expire_all()

        user = await user_repository.get_by_email(email)
        if user and user.spotify_state is None:
            return

    raise TimeoutError()
