import functools
import gzip
import http.server
import lzma
import threading
import xml.etree.ElementTree as ET

import pytest

from tvhplayer.core.guide_feeds import (
    IPTV_EPG_FILE,
    NO_PROGRAMMES,
    NOT_A_GUIDE,
    SHRANK,
    GuideCache,
    GuideError,
    GuideSource,
    GuideSummary,
    build_index,
    epgshare_files,
    find_guides,
    format_time,
    guide_name,
    ids_in_list,
    parse_time,
    summarize,
    write_server_guide,
)
from tvhplayer.core.guide_match import Assignment, GuideChannel

NOW = 1_800_000_000  # 2027-01-15 08:00:00 UTC


def _xmltv(programmes, channels=(('BBCOne.uk', 'BBC One'), ('Dave.uk', 'Dave'))):
    parts = ['<?xml version="1.0" encoding="UTF-8"?>\n<tv>']
    for channel_id, name in channels:
        parts.append(f'<channel id="{channel_id}"><display-name>{name}</display-name></channel>')
    for channel_id, start, stop, title in programmes:
        parts.append(
            f'<programme start="{format_time(start)}" stop="{format_time(stop)}" channel="{channel_id}">'
            f'<title lang="en">{title}</title><desc>About &amp; more</desc></programme>'
        )
    parts.append('</tv>\n')
    return '\n'.join(parts).encode('utf-8')


def _day(channel_id='BBCOne.uk', hours=24, start=NOW):
    return [(channel_id, start + h * 3600, start + (h + 1) * 3600, f'Show {h}') for h in range(hours)]


def test_times_with_and_without_zone():
    assert parse_time('20270115080000 +0000') == (NOW, True)
    assert parse_time('20270115090000 +0100') == (NOW, True)
    assert parse_time('20270115033000 -04:30') == (NOW, True)
    assert parse_time('20270115080000') == (NOW, False)
    assert parse_time('202701150800 Z') == (NOW, True)
    assert parse_time('rubbish') == (None, False)
    assert format_time(NOW) == '20270115080000 +0000'


def test_summary_reads_gzip_and_xz(tmp_path):
    data = _xmltv(_day() + _day('Dave.uk', 2))
    for name, packed in (('g.xml', data), ('g.xml.gz', gzip.compress(data)), ('g.xml.xz', lzma.compress(data))):
        (tmp_path / name).write_bytes(packed)
        summary = summarize(str(tmp_path / name))
        assert summary.programmes == 26
        assert summary.channels['BBCOne.uk'] == {'names': ['BBC One'], 'programmes': 24, 'last': NOW + 24 * 3600}
        assert summary.no_zone == 0


def test_summary_rejects_what_is_not_a_guide(tmp_path):
    for text in ('<html><body>Not found</body></html>', 'not xml at all', ''):
        path = tmp_path / 'bad.xml'
        path.write_text(text)
        with pytest.raises(GuideError) as info:
            summarize(str(path))
        assert str(info.value) == NOT_A_GUIDE


def test_source_settings_round_trip_and_due():
    source = GuideSource.from_dict({'location': ' https://x/g.xml ', 'server': 'builtin', 'hours': 0})
    assert source.location == 'https://x/g.xml'
    assert source.hours == 0
    assert GuideSource.from_dict(source.to_dict()) == source
    assert GuideSource.from_dict({'hours': 'x'}).hours == 12
    assert GuideSource.from_dict(None).location == ''
    fresh = GuideSource('https://x', 'builtin')
    assert fresh.is_due(NOW)
    fresh.tried = NOW - 60
    assert not fresh.is_due(NOW)  # failed a minute ago
    fresh.updated = fresh.tried = NOW - 13 * 3600
    assert fresh.is_due(NOW)
    fresh.hours = 0
    assert not fresh.is_due(NOW)


def test_names():
    assert guide_name('https://iptv-epg.org/files/epg-gb.xml.gz') == 'iptv-epg.org: epg-gb'
    assert guide_name('/home/me/guide.xml') == 'guide.xml'


@pytest.fixture
def web(tmp_path):
    folder = tmp_path / 'web'
    folder.mkdir()
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(folder))
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield folder, f'http://127.0.0.1:{server.server_address[1]}'
    server.shutdown()


def test_cache_keeps_the_last_good_copy(web, tmp_path):
    folder, base = web
    cache = GuideCache(tmp_path / 'cache')
    url = f'{base}/guide.xml.gz'
    (folder / 'guide.xml.gz').write_bytes(gzip.compress(_xmltv(_day(hours=48))))
    assert cache.refresh(url).programmes == 48
    good = open(cache.file(url), 'rb').read()

    (folder / 'guide.xml.gz').write_bytes(gzip.compress(_xmltv(_day(hours=10))))
    with pytest.raises(GuideError) as info:
        cache.refresh(url)
    assert str(info.value) == SHRANK
    (folder / 'guide.xml.gz').write_bytes(_xmltv([]))
    with pytest.raises(GuideError) as info:
        cache.refresh(url)
    assert str(info.value) == NO_PROGRAMMES
    (folder / 'guide.xml.gz').unlink()
    with pytest.raises(GuideError):
        cache.refresh(url)
    assert open(cache.file(url), 'rb').read() == good
    assert cache.summary(url).programmes == 48
    assert [p.name for p in (tmp_path / 'cache').iterdir() if p.suffix == '.part'] == []

    (folder / 'guide.xml.gz').write_bytes(gzip.compress(_xmltv(_day(hours=30))))
    assert cache.refresh(url).programmes == 30


def test_cache_copies_local_files(tmp_path):
    cache = GuideCache(tmp_path / 'cache')
    path = tmp_path / 'mine.xml'
    path.write_bytes(_xmltv(_day(hours=5)))
    assert cache.refresh(str(path)).programmes == 5
    path.write_text('broken')
    with pytest.raises(GuideError):
        cache.refresh(str(path))
    assert cache.summary(str(path)).programmes == 5
    path.unlink()
    with pytest.raises(GuideError):
        cache.refresh(str(path))
    cache.forget(str(path))
    assert cache.summary(str(path)) is None


def _built(tmp_path, assignments, names=None):
    cache = GuideCache(tmp_path / 'cache')
    source = tmp_path / 'g.xml'
    source.write_bytes(_xmltv(_day(hours=3, start=NOW - 3600) + _day('Dave.uk', 2)))
    cache.refresh(str(source))
    index = build_index(cache, [GuideSource(str(source), 'builtin')])
    resolved = {uuid: Assignment(index.find(str(source), guide_id), shift) for uuid, (guide_id, shift) in assignments.items()}
    result = write_server_guide(cache, resolved, names or {}, tmp_path / 'out', now=NOW)
    return result, ET.parse(result.path).getroot()


def test_server_guide_has_one_channel_per_tv_channel(tmp_path):
    result, root = _built(tmp_path, {'u1': ('BBCOne.uk', 0), 'u2': ('BBCOne.uk', 60), 'u3': ('Dave.uk', 0)},
                          {'u1': 'BBC One', 'u2': 'BBC One +1 & Co'})
    assert [c.get('id') for c in root.findall('channel')] == ['tvhplayer.u1', 'tvhplayer.u2', 'tvhplayer.u3']
    assert root.find('channel/display-name').text == 'BBC One (TVHplayer guide)'
    assert root.findall('channel/display-name')[1].text == 'BBC One +1 & Co (TVHplayer guide)'
    starts = {}
    for programme in root.findall('programme'):
        starts.setdefault(programme.get('channel'), []).append(programme.get('start'))
        assert programme.find('desc').text == 'About & more'
    # The programme that ended at NOW is left out; the +1 copy of it still runs.
    assert starts['tvhplayer.u1'] == [format_time(NOW), format_time(NOW + 3600)]
    assert starts['tvhplayer.u2'] == [format_time(NOW), format_time(NOW + 3600), format_time(NOW + 7200)]
    assert result.programmes == {'u1': 2, 'u2': 3, 'u3': 2}
    assert result.last_stop['u2'] == NOW + 3 * 3600


def test_server_guide_without_assignments_is_empty(tmp_path):
    result, root = _built(tmp_path, {})
    assert root.tag == 'tv' and list(root) == []
    assert result.programmes == {}


def test_epgshare_lists():
    html = ''.join(f'<a href="epg_ripper_{n}.xml.gz">epg_ripper_{n}.xml.gz</a>'
                   for n in ('UK1', 'US2', 'US_LOCALS1', 'USA1', 'DE1', 'ALL_SOURCES1'))
    assert epgshare_files(html, ['uk']) == ['UK1']
    assert epgshare_files(html, ['us', 'de']) == ['US2', 'US_LOCALS1', 'DE1']
    text = '202610260537\n\n\n-- epg_ripper_UK1 --\n\n4seven.uk\nBBC.One.HD.uk\n'
    assert ids_in_list(text) == {'4seven.uk', 'bbc.one.hd.uk'}


def test_find_guides_ranks_and_recommends():
    ids = [f'C{n}.uk' for n in range(10)] + ['X.de']
    index = '<a>epg_ripper_UK1.xml.gz</a><a>epg_ripper_DE1.xml.gz</a>'
    lists = {
        'epg_ripper_UK1.txt': '\n'.join(f'C{n}.uk' for n in range(3)),
        'epg_ripper_DE1.txt': 'Other.de',
    }

    def fetch_text(url):
        if url.endswith('/'):
            return index
        return lists[url.rsplit('/', 1)[-1]]

    def fetch_summary(url):
        if url == IPTV_EPG_FILE.format(code='gb'):
            return GuideSummary({f'c{n}.uk': {} for n in range(9)})
        raise GuideError('Could not download the guide.')

    seen = []
    candidates, problems = find_guides(ids, fetch_text, fetch_summary, status=seen.append)
    assert [(c.name, c.matched, c.total, c.recommended) for c in candidates] == [
        ('iptv-epg.org GB', 9, 11, True),
        ('epgshare01 UK1', 3, 11, False),
    ]
    assert problems == []
    assert seen[0] == 'Looking at epgshare01…'


def test_find_guides_reports_unreachable_sites():
    def broken(_url):
        raise OSError('down')

    candidates, problems = find_guides(['A.uk'], broken, lambda url: GuideSummary({'a.uk': {}}))
    assert [c.name for c in candidates] == ['iptv-epg.org GB']
    assert problems == ['epgshare01 could not be reached.']
    assert find_guides(['NoCountry'], broken, broken) == ([], [])


def test_index_uses_good_copies_only(tmp_path):
    cache = GuideCache(tmp_path / 'cache')
    good = tmp_path / 'good.xml'
    good.write_bytes(_xmltv(_day(hours=2)))
    cache.refresh(str(good))
    index = build_index(cache, [GuideSource('https://never.loaded/x.xml', 'builtin'), GuideSource(str(good), 'builtin')])
    assert index.order == [str(good)]
    assert index.find(str(good), 'BBCOne.uk') == GuideChannel(str(good), 'BBCOne.uk', ('BBC One',), 2, NOW + 7200)
