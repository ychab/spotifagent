class UserNotFound(Exception):
    pass


class UserAlreadyExistsException(Exception):
    pass


class EmailAlreadyExistsException(Exception):
    pass


class UserInactive(Exception):
    pass


class InvalidCredentials(Exception):
    pass


class SpotifyAccountNotFoundError(Exception):
    """Raised when an operation requires a linked Spotify account but none exists."""

    pass


class SpotifyExchangeCodeError(Exception):
    pass


class SpotifyPageValidationError(Exception):
    pass
