"""Protocol-agnostic TVHeadend backend interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from .channel_info import NowNext, event_ids_for_channels, match_now_next, next_event_ids
from .dvr import RecordingFile
from .models import (
    PROTOCOL_HTSP,
    AutorecEntry,
    AutorecSpec,
    Channel,
    ChannelTag,
    ConnectionStatus,
    ContentType,
    DvrConfig,
    DvrCutpoint,
    DvrEntry,
    DvrEntryUpdate,
    EpgEvent,
    EpgQuery,
    InputStatus,
    ServerActivity,
    ServerConfig,
    ServerInfo,
    StreamProfile,
    SubscriptionStatus,
    TimerecEntry,
    TimerecSpec,
)


class TvhBackend(ABC):
    """One connection to a TVHeadend server (HTTP JSON or HTSP).

    DVR operations beyond schedule, list, and stop are part of this interface.
    They are not called from the UI. See ``docs/dvr-backend.md``.
    """

    def __init__(self, server: ServerConfig):
        self.server = server

    @abstractmethod
    def close(self):
        """Release sockets/sessions."""

    @abstractmethod
    def get_channels(self) -> List[Channel]:
        """Return the channel list, sorted by number then name."""

    @abstractmethod
    def list_channel_tags(self) -> List[ChannelTag]:
        """Return channel tags, sorted by index then name.

        HTTP ``api/channeltag/grid``. HTSP reads ``tagAdd`` / ``tagUpdate``
        stored during ``enableAsyncMetadata``.
        """

    @abstractmethod
    def query_epg(self, query: EpgQuery) -> List[EpgEvent]:
        """Return guide rows for ``query``.

        HTTP ``api/epg/events/grid``. HTSP uses ``epgQuery`` when a title is
        set, ``getEvents`` for one channel and a limit, and the HTTP grid
        through ``api`` for exact title match, ``mode``, a grid offset, or
        a filter the native call cannot express.
        """

    def get_epg(self, channel: Channel, limit: int = 24) -> List[EpgEvent]:
        """Return upcoming EPG events for one channel."""
        return self.query_epg(EpgQuery(channel=channel, limit=limit))

    @abstractmethod
    def get_event(self, event_id: int) -> EpgEvent:
        """Return one programme.

        HTTP ``api/epg/events/load``. HTSP ``getEvent``. Raises ``TvhError``
        when the server has no such event.
        """

    @abstractmethod
    def load_events(self, event_ids: List[int]) -> List[EpgEvent]:
        """Return several programmes in one request.

        HTTP ``api/epg/events/load`` with ``eventId`` as a JSON list. HTSP
        sends the same path through ``api``. Unknown ids are left out.
        """

    def get_now_next(self, channels: List[Channel]) -> Dict[str, NowNext]:
        """Current and next programme per channel, keyed by ``channel_key``.

        HTSP channels carry ``eventId`` and ``nextEventId``, so one load
        is enough. Otherwise the grid's ``mode=now`` gives the current
        programmes and their ``nextEventId`` values are loaded after.
        """
        ids = event_ids_for_channels(channels)
        if ids:
            events = self.load_events(ids)
        else:
            events = self.query_epg(EpgQuery(mode='now', limit=10000))
            following = next_event_ids(events)
            if following:
                events = events + self.load_events(following)
        return match_now_next(channels, events)

    def list_channel_services(self) -> List[dict]:
        """Service rows that tell radio, HD, and encrypted channels apart.

        HTTP ``mpegts/service/grid`` with ``channel``, ``dvb_servicetype``,
        ``encrypted``, and ``provider``. The grid needs admin rights; HTSP
        sends the same facts with each channel, so it returns nothing.
        """
        return []

    @abstractmethod
    def list_related_events(self, event_id: int) -> List[EpgEvent]:
        """Return other broadcasts in the same series.

        HTTP ``api/epg/events/related``. HTSP calls that path through ``api``.
        """

    @abstractmethod
    def list_alternative_events(self, event_id: int) -> List[EpgEvent]:
        """Return other broadcasts of the same event.

        HTTP ``api/epg/events/alternative``. HTSP calls that path through ``api``.
        """

    @abstractmethod
    def list_content_types(self) -> List[ContentType]:
        """Return genre ids from ``api/epg/content_type/list``.

        HTSP reads the same path through ``api``.
        """

    @abstractmethod
    def list_profiles(self) -> List[StreamProfile]:
        """Return streaming profiles.

        HTTP ``api/profile/list``. HTSP ``getProfiles``.
        """

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
        """Return DVR entries from the combined grid.

        HTTP ``dvr/entry/grid`` includes upcoming, running, finished, failed,
        and removed rows. HTSP returns the entries received as
        ``dvrEntryAdd`` / ``dvrEntryUpdate``. Removed rows alone are
        ``list_removed_dvr_entries``.
        """

    @abstractmethod
    def stop_dvr_entry(self, entry: DvrEntry) -> None:
        """Stop an in-progress recording and keep the file.

        HTTP ``dvr/entry/stop``. HTSP ``stopDvrEntry`` (the call this client
        already sends; the published HTSP method list documents
        ``cancelDvrEntry`` as the cancel path). A running entry that should
        be classified as failed is ``cancel_dvr_entry``.
        """

    @abstractmethod
    def cancel_dvr_entry(self, entry: DvrEntry) -> None:
        """Drop a scheduled timer, or abort a running recording.

        A running recording stays on disk and is classified as failed.
        HTTP ``dvr/entry/cancel``. HTSP ``cancelDvrEntry`` cancels and leaves
        the database row in place.
        """

    @abstractmethod
    def remove_dvr_entry(self, entry: DvrEntry) -> None:
        """Delete a completed recording from storage.

        HTTP ``dvr/entry/remove``. HTSP sends that same HTTP path through the
        ``api`` proxy. ``delete_dvr_entry`` removes the database row and does
        not promise to delete the file.
        """

    @abstractmethod
    def delete_dvr_entry(self, entry: DvrEntry) -> None:
        """Remove the recording's database record.

        HTTP ``idnode/delete`` with the entry UUID. The idnode docs warn that
        deleting records can discard data. HTSP ``deleteDvrEntry`` removes the
        database entry; that method does not promise file deletion.
        """

    @abstractmethod
    def set_dvr_rerecord(self, entry: DvrEntry, action: str) -> None:
        """Allow, deny, or toggle re-recording a finished or failed entry.

        ``action`` is ``allow``, ``deny``, or ``toggle``. HTTP
        ``dvr/entry/rerecord/<action>``. HTSP uses the same path via ``api``.
        """

    @abstractmethod
    def set_dvr_prevrec(self, entry: DvrEntry, action: str) -> None:
        """Mark an upcoming timer previously recorded, or create it again.

        ``action`` is ``set``, ``unset``, or ``toggle``. Set marks the timer
        completed and flags the file deleted. Unset creates a new timer.
        HTTP ``dvr/entry/prevrec/<action>`` with ``uuid``. The DVR page does
        not list parameters for these three calls; ``uuid`` is the parameter
        documented for the sibling cancel, remove, and rerecord calls.
        HTSP uses the same HTTP path via ``api``.
        """

    @abstractmethod
    def update_dvr_entry(self, entry: DvrEntry, update: DvrEntryUpdate) -> None:
        """Replace the supplied fields on one DVR entry.

        HTTP ``idnode/save`` (``node`` JSON, language maps for text, ``pri``
        for priority). HTSP ``updateDvrEntry``. See ``DvrEntryUpdate`` for units.
        """

    @abstractmethod
    def move_dvr_entry(self, entry: DvrEntry, category: str) -> None:
        """Move a finished entry between the Finished and Failed lists.

        ``category`` is ``finished`` or ``failed``. The file is not moved.
        HTTP ``dvr/entry/move/finished`` or ``dvr/entry/move/failed``.
        HTSP uses the same path via ``api``.
        """

    @abstractmethod
    def recording_url(self, entry: DvrEntry) -> str:
        """HTTP URL the player can open for a stored recording.

        HTTP uses the entry ``url`` (``dvrfile/<uuid>``) and embeds basic
        auth when credentials are configured. HTSP calls ``getTicket`` with
        ``dvrId`` and appends ``ticket`` to that path, without basic auth.
        The ticket path is used as returned; it already includes any webroot.
        """

    @abstractmethod
    def open_recording(self, entry: DvrEntry) -> RecordingFile:
        """Open the recording for ``read``, ``seek``, ``stat``, and ``close``.

        HTTP uses Range requests against the dvrfile URL. HTSP uses
        ``fileOpen`` on ``/dvrfile/<id>``, then ``fileRead``, ``fileSeek``,
        ``fileStat``, and ``fileClose``. The HTSP handle is valid while this
        backend connection stays open.
        """

    @abstractmethod
    def get_dvr_cutpoints(self, entry: DvrEntry) -> List[DvrCutpoint]:
        """Return HTSP cutpoints for one recording.

        HTSP ``getDvrCutpoints``. The JSON API does not document cutpoints;
        the HTTP backend raises ``TvhError``.
        """

    @abstractmethod
    def notify_dvr_file_moved(self, src: str, dst: str) -> None:
        """Tell the server a recording file was relocated on disk.

        HTTP ``dvr/entry/filemoved`` with ``src`` and ``dst``. Requires the
        ADMIN privilege. HTSP sends the same path via ``api``.
        """

    @abstractmethod
    def list_dvr_configs(self) -> List[DvrConfig]:
        """Return DVR profiles from ``dvr/config/grid``.

        HTSP ``getDvrConfigs`` only returns uuid, name, and comment, so the
        HTSP backend reads the HTTP grid through ``api`` and returns the
        same ``DvrConfig`` records as the HTTP backend.
        """

    @abstractmethod
    def list_removed_dvr_entries(self) -> List[DvrEntry]:
        """Return the removed-recordings log (``dvr/entry/grid_removed``).

        Empty when the server is configured to delete the log with the file.
        """

    @abstractmethod
    def create_dvr_entry_by_event(self, event_id: int, config_uuid: str = '') -> str:
        """Schedule a timer from an EPG event id.

        HTTP ``dvr/entry/create_by_event`` (``event_id``, optional
        ``config_uuid``). HTSP ``addDvrEntry`` with ``eventId`` and optional
        ``configName``. Returns the server id when the response includes one.
        """

    @abstractmethod
    def list_autorec_entries(self) -> List[AutorecEntry]:
        """Return series timers from ``dvr/autorec/grid``.

        HTSP has no list RPC for autorec entries, so it reads this grid
        through ``api``.
        """

    @abstractmethod
    def create_autorec_entry(self, spec: AutorecSpec) -> str:
        """Create a series timer. ``spec.title`` is required.

        HTTP ``dvr/autorec/create`` with ``conf``. HTSP ``addAutorecEntry``.
        Returns the HTTP uuid or the HTSP id string when the server sends one.
        """

    @abstractmethod
    def update_autorec_entry(self, entry: AutorecEntry, spec: AutorecSpec) -> None:
        """Update a series timer. Only fields set on ``spec`` are sent.

        HTTP ``idnode/save``. HTSP ``updateAutorecEntry`` when ``entry.htsp_id``
        is set, otherwise the HTTP save through ``api`` (grid rows have a uuid
        and no HTSP id).
        """

    @abstractmethod
    def delete_autorec_entry(self, entry: AutorecEntry) -> None:
        """Delete a series timer and its pending timers.

        HTTP ``idnode/delete``. HTSP ``deleteAutorecEntry`` when ``htsp_id``
        is set, otherwise ``idnode/delete`` through ``api``.
        """

    @abstractmethod
    def create_autorec_by_series(self, event_id: int, config_uuid: str = '') -> str:
        """Create a series timer from an EPG event's series link.

        Both protocols call HTTP ``dvr/autorec/create_by_series``. HTSP has
        no native create-by-series RPC, so it uses the ``api`` proxy.
        """

    @abstractmethod
    def list_timerec_entries(self) -> List[TimerecEntry]:
        """Return time-based timers from ``dvr/timerec/grid``.

        HTSP reads this grid through ``api``.
        """

    @abstractmethod
    def create_timerec_entry(self, spec: TimerecSpec) -> str:
        """Create a time-based timer. ``spec.title`` is required.

        HTTP ``dvr/timerec/create`` with ``conf`` (``HH:MM`` times). HTSP
        ``addTimerecEntry`` (minutes from midnight). Returns the server id
        when the response includes one.
        """

    @abstractmethod
    def update_timerec_entry(self, entry: TimerecEntry, spec: TimerecSpec) -> None:
        """Update a time-based timer. Only fields set on ``spec`` are sent.

        HTTP ``idnode/save``. HTSP ``updateTimerecEntry`` when ``htsp_id`` is
        set, otherwise the HTTP save through ``api``.
        """

    @abstractmethod
    def delete_timerec_entry(self, entry: TimerecEntry) -> None:
        """Delete a time-based timer.

        HTTP ``idnode/delete``. HTSP ``deleteTimerecEntry`` when ``htsp_id``
        is set, otherwise ``idnode/delete`` through ``api``.
        """

    @abstractmethod
    def get_server_info(self) -> ServerInfo:
        """Return server name/version/capabilities."""

    @abstractmethod
    def get_inputs(self) -> List[InputStatus]:
        """Return tuner rows from ``status/inputs``.

        Each row keeps the JSON payload. ``.get('input')`` and
        ``.get('signal')`` are the keys the status window already reads.
        HTSP loads this grid through ``api``.
        """

    @abstractmethod
    def get_connections(self) -> List[ConnectionStatus]:
        """Return client connections from ``status/connections``.

        ``.get('peer')``, ``.get('user')``, and ``.get('started')`` read the
        original row. HTSP loads this grid through ``api``.
        """

    @abstractmethod
    def get_subscriptions(self) -> List[SubscriptionStatus]:
        """Return live subscriptions from ``status/subscriptions``.

        ``.get('channel')`` returns the original value, including a dict.
        HTSP loads this grid through ``api``.
        """

    @abstractmethod
    def get_activity(self) -> ServerActivity:
        """Return the low-power activity summary from ``status/activity``.

        Requires Tvheadend 4.3-2405 or later. HTSP reads the same path
        through ``api``.
        """

    @abstractmethod
    def stream_url(self, channel: Channel, profile: Optional[str] = None) -> str:
        """HTTP URL mpv/ffmpeg can play (HTSP muxpkt is not used).

        HTTP uses ``/stream/channel/{uuid}``. HTSP uses the
        ``/stream/channelid/{id}`` path and ticket from ``getTicket``, so
        digest-only servers work; without a ticket it embeds basic auth.
        ``profile`` is added as ``?profile=`` when set.
        """

    @abstractmethod
    def image_url(self, reference: str) -> str:
        """HTTP URL for a channel icon or programme image reference.

        ``imagecache/38`` and other relative paths are joined to the server
        and carry embedded basic auth. An absolute http(s) URL is returned
        unchanged. An empty reference returns ``''``.
        """

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
