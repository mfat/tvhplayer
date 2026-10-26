from tvhplayer.core.guide_match import (
    PLUS_ONE_SHIFT,
    Choice,
    GuideChannel,
    GuideIndex,
    ServerChannel,
    assign,
    clean_name,
    id_country,
    main_region,
    normalize_id,
)


def test_ids_compare_without_case_or_feed():
    assert normalize_id(' BBCOne.uk@HD ') == 'bbcone.uk'
    assert normalize_id('BBC.One.HD.uk') == 'bbc.one.hd.uk'
    assert id_country('BBCOne.uk@SD') == 'uk'
    assert id_country('Fox.us@WFTXTV') == 'us'
    # A regional feed has a schedule of its own.
    assert normalize_id('HBO.us@West') == 'hbo.us@west'
    assert normalize_id('Fox.us@WFTXTV') != normalize_id('Fox.us')
    assert id_country('Das Erste') == ''


def test_names_lose_region_quality_and_plus_one():
    assert clean_name('UK: BBC One HD') == ('bbc one', False)
    assert clean_name('|UK| E4 +1') == ('e4', True)
    assert clean_name('[DE] Das Erste FHD') == ('das erste', False)
    assert clean_name('5USA+1') == ('5usa', True)
    assert clean_name('Film4 Plus 1') == ('film4', True)
    assert clean_name('Sky Sports: F1') == ('sky sports f1', False)
    assert clean_name('Tom & Jerry') == ('tom and jerry', False)


def _guide(*channels):
    return GuideIndex([GuideChannel(*channel) for channel in channels], ['a', 'b'])


def test_exact_id_wins_in_source_order():
    index = _guide(
        ('b', 'BBCOne.uk', ('BBC One',), 50),
        ('a', 'bbcone.uk', ('BBC One',), 10),
    )
    channels = [ServerChannel('u1', 'BBC One HD', epg_ids=('BBCOne.uk@HD',)),
                ServerChannel('u2', 'BBC One', epg_ids=('BBCOne.uk',)),
                ServerChannel('u3', 'Dave')]
    result = assign(channels, index, {})
    assert result['u1'].channel.source == 'a'
    assert result['u2'].channel.source == 'a'
    assert result['u1'].how == 'id'
    assert 'u3' not in result


def test_names_are_never_used_without_a_choice():
    index = _guide(('a', 'Dave.uk', ('Dave',), 5))
    assert assign([ServerChannel('u1', 'Dave')], index, {}) == {}


def test_choices_override_and_fall_back_to_id():
    index = _guide(('a', 'BBCOne.uk', ('BBC One',), 5), ('b', 'Dave.uk', ('Dave',), 5))
    channel = ServerChannel('u1', 'BBC One', epg_ids=('BBCOne.uk',))
    chosen = assign([channel], index, {'u1': Choice('b', 'Dave.uk', 60)})['u1']
    assert (chosen.channel.id, chosen.shift, chosen.how) == ('Dave.uk', 60, 'chosen')
    assert assign([channel], index, {'u1': Choice()}) == {}
    gone = assign([channel], index, {'u1': Choice('c', 'Gone.uk')})['u1']
    assert gone.channel.id == 'BBCOne.uk'


def test_suggestions_prefer_exact_names_and_the_region():
    index = _guide(
        ('a', 'FOX.us', ('FOX',), 5),
        ('a', 'FOX.uk', ('FOX',), 5),
        ('a', 'FoxNews.us', ('Fox News',), 5),
    )
    channel = ServerChannel('u1', 'UK: FOX HD')
    suggestions = index.suggest(channel, region='uk')
    assert [s.channel.id for s in suggestions[:2]] == ['FOX.uk', 'FOX.us']
    assert suggestions[0].score > suggestions[1].score
    assert all(s.channel.id != 'FoxNews.us' for s in suggestions)


def test_plus_one_channel_reuses_the_main_guide_an_hour_later():
    index = _guide(('a', 'E4.uk', ('E4',), 5))
    suggestions = index.suggest(ServerChannel('u1', 'E4 +1'))
    assert suggestions[0].channel.id == 'E4.uk'
    assert suggestions[0].shift == PLUS_ONE_SHIFT
    # A "+1" guide is never offered for the channel itself.
    index = _guide(('a', 'E4Plus1.uk', ('E4 +1',), 5))
    assert index.suggest(ServerChannel('u1', 'E4')) == []


def test_similar_names_are_suggested_lower():
    index = _guide(('a', 'Nickelodeon.uk', ('Nickelodeon',), 5))
    suggestions = index.suggest(ServerChannel('u1', 'Nickelodeonn'))
    assert suggestions and suggestions[0].reason == 'similar name'
    assert suggestions[0].score < 0.94


def test_search_and_region():
    index = _guide(('a', 'BBCOne.uk', ('BBC One',), 5), ('a', 'Dave.uk', ('Dave',), 5))
    assert [c.id for c in index.search('bbc')] == ['BBCOne.uk']
    assert index.search('') == []
    channels = [ServerChannel('1', 'x', epg_ids=('A.uk',)), ServerChannel('2', 'y', epg_ids=('B.uk', 'C.de'))]
    assert main_region(channels) == 'uk'


def test_choice_round_trip():
    assert Choice.from_dict({'source': 's', 'id': 'i', 'shift': '60'}) == Choice('s', 'i', 60)
    assert Choice.from_dict('junk') is None
    assert Choice.from_dict(Choice('s', '', 0).to_dict()) == Choice('s', '', 0)
