from pydantic import EmailStr

from spotifagent.application.use_cases.user_create import user_create
from spotifagent.domain.entities.users import User
from spotifagent.domain.entities.users import UserCreate
from spotifagent.infrastructure.entrypoints.cli.dependencies import get_db
from spotifagent.infrastructure.entrypoints.cli.dependencies import get_password_hasher
from spotifagent.infrastructure.entrypoints.cli.dependencies import get_user_repository


async def user_create_logic(email: EmailStr, password: str) -> User:
    password_hasher = get_password_hasher()

    async with get_db() as session:
        user = await user_create(
            user_data=UserCreate(email=email, password=password),
            user_repository=get_user_repository(session),
            password_hasher=password_hasher,
        )

    return user
