class TvhError(Exception):
    """Error talking to a TVHeadend server."""


class TvhConnectionError(TvhError):
    """Network or protocol transport failure."""


class TvhAuthError(TvhError):
    """Server rejected the credentials."""


class TvhProtocolError(TvhError):
    """Malformed HTSP/HTTP payload."""


class PlaylistError(Exception):
    """A playlist could not be read or imported. The message is shown to the user."""
