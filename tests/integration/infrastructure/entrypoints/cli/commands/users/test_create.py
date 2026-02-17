from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spotifagent.domain.ports.security import PasswordHasherPort
from spotifagent.infrastructure.adapters.database.models import User as UserModel
from spotifagent.infrastructure.entrypoints.cli.commands.users import user_create_logic


class TestUserCreateLogic:
    async def test__nominal(
        self,
        async_session_db: AsyncSession,
        password_hasher: PasswordHasherPort,
    ) -> None:
        email = "test@example.com"
        password = "testtest"

        user = await user_create_logic(email, password)
        assert user is not None

        stmt = select(UserModel).where(UserModel.email == email)
        result = await async_session_db.execute(stmt)
        user_db = result.scalar_one()

        assert user_db is not None
        assert user_db.id == user.id
        assert user_db.email == user.email == email
        assert user_db.is_active is True
        assert password_hasher.verify(password, user_db.hashed_password) is True
