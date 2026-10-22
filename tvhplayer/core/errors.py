class TvhError(Exception):
    """Error talking to a TVHeadend server."""


class TvhConnectionError(TvhError):
    """Network or protocol transport failure."""


class TvhAuthError(TvhError):
    """Server rejected the credentials."""


class TvhProtocolError(TvhError):
    """Malformed HTSP/HTTP payload."""
