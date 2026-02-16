from faker import Faker
from polyfactory.factories.sqlalchemy_factory import SQLAlchemyFactory
from polyfactory.factories.sqlalchemy_factory import T

from spotifagent.infrastructure.config.settings.app import app_settings


class BaseModelFactory(SQLAlchemyFactory[T]):
    __is_base_factory__ = True

    __use_defaults__ = True
    __set_as_default_factory_for_type__ = True

    __faker__ = Faker(locale=app_settings.LOCALE)

    # We intentionally disable the Polyfactory relationships mechanism due to
    # the usage of MappedAsDataclass with init=False on relationship fields.
    __set_relationships__ = False
    __set_association_proxy__ = False
