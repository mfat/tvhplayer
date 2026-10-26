"""Change channels on the server: number, name, hidden, and favourites. No Qt imports.

These need the admin privilege, so they go through ``TvhAdmin`` over HTTP
on every server, HTSP ones included. HTSP names a channel or tag by a short
id that Tvheadend takes from the first four bytes of its uuid, which is how
an HTSP channel finds its row here.
"""

from __future__ import annotations

import re
import struct
from typing import Iterable, List, Optional

from .errors import TvhError
from .models import Channel, ChannelTag

FAVOURITES = 'Favourites'
_UUID = re.compile(r'^[0-9a-fA-F]{32}$')
_NUMBER = re.compile(r'^\d{1,6}(\.\d{1,5})?$')


def short_id(uuid: str) -> Optional[int]:
    """The id HTSP uses for the idnode with this uuid."""
    if not _UUID.match(uuid or ''):
        return None
    return struct.unpack('<I', bytes.fromhex(uuid)[:4])[0] & 0x7FFFFFFF


def find_row(rows: Iterable[dict], uuid: str, htsp_id: Optional[int]) -> Optional[dict]:
    rows = list(rows)
    for row in rows:
        if uuid and row.get('uuid') == uuid:
            return row
    if htsp_id is None:
        return None
    return next((row for row in rows if short_id(row.get('uuid') or '') == htsp_id), None)


def favourites_tag(tags: Iterable[ChannelTag]) -> Optional[ChannelTag]:
    return next((tag for tag in tags if tag.name == FAVOURITES), None)


def is_favourite(channel: Channel, tags: Iterable[ChannelTag]) -> bool:
    tag = favourites_tag(tags)
    if tag is None:
        return False
    ids = {tag.uuid}
    if tag.htsp_id is not None:
        ids.add(str(tag.htsp_id))
    return any(tag_id in ids for tag_id in channel.tag_ids)


def check_number(text: str) -> str:
    """``text`` as Tvheadend writes a channel number, such as ``12`` or ``12.1``."""
    text = (text or '').strip()
    if not _NUMBER.match(text):
        raise ValueError('Use a number such as 12 or 12.1')
    major, _dot, minor = text.partition('.')
    major = str(int(major))
    if minor and int(minor):
        return f'{major}.{int(minor)}'
    return major


def number_text(channel: Channel) -> str:
    if channel.number_minor:
        return f'{channel.number}.{channel.number_minor}'
    return str(channel.number or '')


class ChannelEditor:
    """One change at a time to the server's channels, through a ``TvhAdmin``."""

    def __init__(self, admin):
        self._admin = admin

    def _row(self, channel: Channel) -> dict:
        row = find_row(self._admin.list_channels(), channel.uuid, channel.htsp_id)
        if row is None or not row.get('uuid'):
            raise TvhError(f'The server has no channel {channel.name}')
        return row

    def set_number(self, channel: Channel, number: str) -> None:
        row = self._row(channel)
        self._admin.save([{'uuid': row['uuid'], 'number': check_number(number)}])

    def rename(self, channel: Channel, name: str) -> None:
        name = (name or '').strip()
        if not name:
            raise ValueError('The name cannot be empty')
        row = self._row(channel)
        # A name taken from the network would come back on the next scan.
        self._admin.save([{'uuid': row['uuid'], 'name': name, 'autoname': False}])

    def set_enabled(self, channel: Channel, enabled: bool) -> None:
        row = self._row(channel)
        self._admin.save([{'uuid': row['uuid'], 'enabled': bool(enabled)}])

    def set_favourite(self, channel: Channel, favourite: bool) -> None:
        row = self._row(channel)
        tag_uuid = self._favourites_uuid(create=favourite)
        if not tag_uuid:
            return
        tags: List[str] = [tag for tag in row.get('tags') or [] if tag != tag_uuid]
        if favourite:
            tags.append(tag_uuid)
        if tags != list(row.get('tags') or []):
            self._admin.save([{'uuid': row['uuid'], 'tags': tags}])

    def _favourites_uuid(self, create: bool) -> str:
        for row in self._admin.list_channel_tags():
            if row.get('name') == FAVOURITES and row.get('uuid'):
                if create and not row.get('enabled', True):
                    self._admin.save([{'uuid': row['uuid'], 'enabled': True}])
                return row['uuid']
        if not create:
            return ''
        return self._admin.create_channel_tag({
            'name': FAVOURITES,
            'enabled': True,
            'comment': 'Channels marked as favourites in TVHplayer',
        })
