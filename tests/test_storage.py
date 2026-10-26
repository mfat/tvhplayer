from tvhplayer.core.storage import GB, format_size, free_bytes, low_space_message


def test_low_space_message():
    assert low_space_message(10 * GB, 5) == ''
    assert low_space_message(int(3.2 * GB), 5) == 'Only 3.2 GB free for recordings'
    assert low_space_message(400 * 1000 ** 2, 5) == 'Only 400 MB free for recordings'
    assert low_space_message(1, 0) == ''
    assert low_space_message(None, 5) == ''


def test_format_size_and_free_bytes(tmp_path):
    assert format_size(250 * GB) == '250 GB'
    assert free_bytes(str(tmp_path)) > 0
    assert free_bytes(str(tmp_path / 'missing')) is None
    assert free_bytes('') is None
