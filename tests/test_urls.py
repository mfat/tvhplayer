from tvhplayer.core.urls import (
    http_auth,
    http_base_url,
    htsp_host_port,
    insert_basic_auth,
)


def test_http_base_adds_scheme_and_strips_slash():
    assert http_base_url('127.0.0.1:9981') == 'http://127.0.0.1:9981'
    assert http_base_url('http://tvh.example:9981/') == 'http://tvh.example:9981'


def test_htsp_port_defaults_to_9982():
    assert htsp_host_port('http://192.168.8.1:9981') == ('192.168.8.1', 9982)
    assert htsp_host_port('http://192.168.8.1:9981', 9983) == ('192.168.8.1', 9983)


def test_insert_basic_auth():
    url = insert_basic_auth('http://127.0.0.1:9981/stream/channel/abc', 'user', 'secret')
    assert url == 'http://user:secret@127.0.0.1:9981/stream/channel/abc'


def test_http_auth_none_when_empty():
    assert http_auth({'username': '', 'password': ''}) is None
    assert http_auth({'username': 'u', 'password': ''}) == ('u', '')
