import pytest

from tvhplayer.core.channel_edit import (
    FAVOURITES,
    ChannelEditor,
    check_number,
    find_row,
    is_favourite,
    number_text,
    short_id,
)
from tvhplayer.core.models import Channel, ChannelTag

TV3 = '5cac570dfa921f018d748b18105ca79a'


class FakeAdmin:
    def __init__(self, channels, tags):
        self.channels = channels
        self.tags = tags
        self.saved = []
        self.created = []

    def list_channels(self):
        return self.channels

    def list_channel_tags(self):
        return self.tags

    def create_channel_tag(self, conf):
        self.created.append(conf)
        return 'fav'

    def save(self, nodes):
        self.saved.extend(nodes)


def test_short_id_matches_htsp_channel_ids():
    # Read from a real server: TV3 is channelId 223849564 over HTSP.
    assert short_id(TV3) == 223849564
    assert short_id('not-a-uuid') is None
    rows = [{'uuid': 'a' * 32}, {'uuid': TV3}]
    assert find_row(rows, '223849564', 223849564) is rows[1]
    assert find_row(rows, TV3, None) is rows[1]
    assert find_row(rows, 'x', None) is None


def test_numbers():
    assert check_number(' 012 ') == '12'
    assert check_number('12.1') == '12.1'
    assert check_number('12.0') == '12'
    for bad in ('', 'abc', '-1', '1.2.3'):
        with pytest.raises(ValueError):
            check_number(bad)
    assert number_text(Channel(uuid='u', name='n', number=7, number_minor=2)) == '7.2'
    assert number_text(Channel(uuid='u', name='n', number=7)) == '7'


def test_favourites_tag_is_created_once_and_toggled():
    channel = Channel(uuid='223849564', name='TV3', htsp_id=223849564)
    admin = FakeAdmin([{'uuid': TV3, 'tags': ['news']}], [])
    editor = ChannelEditor(admin)
    editor.set_favourite(channel, True)
    assert admin.created[0]['name'] == FAVOURITES
    assert admin.saved == [{'uuid': TV3, 'tags': ['news', 'fav']}]

    admin = FakeAdmin([{'uuid': TV3, 'tags': ['news', 'fav']}], [{'uuid': 'fav', 'name': FAVOURITES}])
    ChannelEditor(admin).set_favourite(channel, False)
    assert admin.created == []
    assert admin.saved == [{'uuid': TV3, 'tags': ['news']}]

    # Removing when there is no Favourites tag changes nothing.
    admin = FakeAdmin([{'uuid': TV3, 'tags': []}], [])
    ChannelEditor(admin).set_favourite(channel, False)
    assert admin.saved == [] and admin.created == []


def test_number_name_and_hiding_are_saved():
    channel = Channel(uuid=TV3, name='TV3')
    admin = FakeAdmin([{'uuid': TV3}], [])
    editor = ChannelEditor(admin)
    editor.set_number(channel, '4.1')
    editor.rename(channel, ' TV Three ')
    editor.set_enabled(channel, False)
    assert admin.saved == [
        {'uuid': TV3, 'number': '4.1'},
        {'uuid': TV3, 'name': 'TV Three', 'autoname': False},
        {'uuid': TV3, 'enabled': False},
    ]
    with pytest.raises(Exception):
        ChannelEditor(FakeAdmin([], [])).set_enabled(channel, True)


def test_is_favourite_over_http_and_htsp():
    tags = [ChannelTag(uuid='fav', name=FAVOURITES, htsp_id=5)]
    assert is_favourite(Channel(uuid='u', name='n', tag_ids=['fav']), tags)
    assert is_favourite(Channel(uuid='u', name='n', tag_ids=['5']), tags)
    assert not is_favourite(Channel(uuid='u', name='n', tag_ids=['6']), tags)
    assert not is_favourite(Channel(uuid='u', name='n', tag_ids=['fav']), [])
