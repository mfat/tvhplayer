"""Protocol-agnostic TVHeadend backend interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from .models import PROTOCOL_HTSP, Channel, DvrEntry, EpgEvent, ServerConfig, ServerInfo


class TvhBackend(ABC):
    """One connection to a TVHeadend server (HTTP JSON or HTSP)."""

    def __init__(self, server: ServerConfig):
        self.server = server

    @abstractmethod
    def close(self):
        """Release sockets/sessions."""

    @abstractmethod
    def get_channels(self) -> List[Channel]:
        """Return the channel list, sorted by number then name."""

    @abstractmethod
    def get_epg(self, channel: Channel, limit: int = 24) -> List[EpgEvent]:
        """Return upcoming EPG events for one channel."""

    @abstractmethod
    def create_dvr_entry(
        self,
        channel: Channel,
        start: int,
        stop: int,
        title: str,
        description: str = '',
        comment: str = '',
        event_id: Optional[int] = None,
    ) -> None:
        """Schedule or start a server-side recording."""

    @abstractmethod
    def list_dvr_entries(self) -> List[DvrEntry]:
        """Return DVR entries (upcoming, running, finished, failed)."""

    @abstractmethod
    def stop_dvr_entry(self, entry: DvrEntry) -> None:
        """Stop an in-progress recording without deleting the file."""

    @abstractmethod
    def get_server_info(self) -> ServerInfo:
        """Return server name/version/capabilities."""

    @abstractmethod
    def get_inputs(self) -> list:
        """Return tuner/input status rows (JSON `status/inputs` shape)."""

    @abstractmethod
    def get_connections(self) -> list:
        """Return client connections (`status/connections`)."""

    @abstractmethod
    def get_subscriptions(self) -> list:
        """Return live subscriptions (`status/subscriptions`)."""

    @abstractmethod
    def stream_url(self, channel: Channel) -> str:
        """HTTP URL VLC/ffmpeg can play (HTSP muxpkt is not used)."""

    def ping(self) -> None:
        """Cheap connectivity check; default is get_server_info()."""
        self.get_server_info()


def create_backend(server) -> TvhBackend:
    """Build an HTTP or HTSP backend from a server dict or ServerConfig."""
    if isinstance(server, dict):
        config = ServerConfig.from_dict(server)
    else:
        config = server
    if config.protocol == PROTOCOL_HTSP:
        from .htsp_backend import HtspBackend

        return HtspBackend(config)
    from .http_backend import HttpBackend

    return HttpBackend(config)


def channel_sort_key(channel: Channel):
    number = channel.number if channel.number else float('inf')
    return (number, (channel.name or '').lower())
