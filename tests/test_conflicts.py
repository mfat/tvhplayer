from tvhplayer.core.channel_edit import short_id
from tvhplayer.core.conflicts import TunerUse, conflict_key, find_conflicts, read_tuner_use
from tvhplayer.core.models import DvrEntry
from tvhplayer.core.tuners import read_tuners, tuner_kind

A = 'a' * 32
B = 'b' * 32
C = 'c' * 32
HOUR = 3600


def entry(uuid, channel, start, duration=HOUR, status='Scheduled', **raw):
    return DvrEntry(uuid=uuid, title=uuid, channel_name='c', start=start, duration=duration, status=status,
                    raw=dict(raw, channel=channel))


def test_tuner_kinds():
    assert tuner_kind('linuxdvb_frontend_dvbt') == 'DVB-T'
    assert tuner_kind('satip_frontend_dvbs_slave') == 'DVB-S'
    assert tuner_kind('tvhdhomerun_frontend_atsc_t') == 'ATSC-T'
    assert tuner_kind('linuxdvb_adapter') == ''


class Admin:
    tree = {
        'root': [{'uuid': 'ad0', 'text': 'Adapter 0', 'class': 'linuxdvb_adapter', 'leaf': 0}],
        'ad0': [
            {'uuid': 'fe0', 'text': 'DVB-T #0', 'class': 'linuxdvb_frontend_dvbt', 'leaf': 0,
             'params': [{'id': 'enabled', 'value': True}, {'id': 'networks', 'value': ['net']}]},
            {'uuid': 'fe1', 'text': 'DVB-C #1', 'class': 'linuxdvb_frontend_dvbc', 'leaf': 1,
             'params': [{'id': 'enabled', 'value': False}]},
        ],
        'fe0': [],
    }

    def hardware_tree(self, uuid='root'):
        return self.tree.get(uuid, [])

    def list_tuner_muxes(self):
        return [{'uuid': 'm1'}, {'uuid': 'm2'}]

    def list_services_all(self):
        return [
            {'multiplex_uuid': 'm1', 'channel': [A]},
            {'multiplex_uuid': 'm2', 'channel': [B]},
            {'multiplex_uuid': 'iptv', 'channel': [C]},
        ]


def test_read_tuners_and_use():
    tuners = read_tuners(Admin())
    assert [(t.name, t.kind, t.enabled, t.hardware, t.networks) for t in tuners] == [
        ('DVB-T #0', 'DVB-T', True, 'Adapter 0', ['net']),
        ('DVB-C #1', 'DVB-C', False, 'Adapter 0', []),
    ]
    use = read_tuner_use(Admin())
    assert use.tuners == 1
    assert use.channel_mux == {A: 'm1', B: 'm2'}
    assert use.mux_of(short_id(B)) == 'm2'
    assert use.mux_of(C) is None


def test_overlaps_on_more_muxes_than_tuners():
    use = TunerUse(tuners=1, channel_mux={A: 'm1', B: 'm2', C: 'm1'}, short_ids={short_id(B): B})
    first = entry('first', A, 1000)
    second = entry('second', short_id(B), 1000 + HOUR // 2)
    same_mux = entry('same', C, 1000)
    later = entry('later', B, 1000 + 2 * HOUR)
    groups = find_conflicts([first, second, same_mux, later], use, now=0)
    assert [[e.uuid for e in group] for group in groups] == [['first', 'same', 'second']]
    assert conflict_key(groups[0]) == {'first', 'same', 'second'}
    # Two tuners are enough; finished, disabled, and past recordings do not count.
    assert find_conflicts([first, second], TunerUse(2, use.channel_mux, use.short_ids), 0) == []
    assert find_conflicts([first, entry('done', B, 1000, status='Completed OK')], use, 0) == []
    assert find_conflicts([first, entry('off', B, 1000, enabled=False)], use, 0) == []
    assert find_conflicts([first, second], use, now=10 * HOUR) == []
    assert find_conflicts([first, second], None, 0) == []
