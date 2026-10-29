import base64
import pytest
from urllib.parse import unquote, urlparse

from requests import Request

from tvhplayer.core.logs import sanitize
from tvhplayer.core.urls import (
    TvhHttpAuth,
    http_auth,
    http_base_url,
    htsp_host_port,
    pin_http_port,
    insert_basic_auth,
)


def test_http_base_adds_scheme_and_strips_slash():
    assert http_base_url('127.0.0.1:9981') == 'http://127.0.0.1:9981'
    assert http_base_url('http://tvh.example:9981/') == 'http://tvh.example:9981'


def test_htsp_port_defaults_to_9982():
    assert htsp_host_port('http://192.168.8.1:9981') == ('192.168.8.1', 9982)
    assert htsp_host_port('http://192.168.8.1:9981', 9983) == ('192.168.8.1', 9983)


def test_missing_http_port_defaults_to_tvheadend_port():
    assert http_base_url('myserver') == 'http://myserver:9981'
    assert http_base_url('http://tvh.example') == 'http://tvh.example:9981'
    assert http_base_url('http://tvh.example/tvh/') == 'http://tvh.example:9981/tvh'
    assert http_base_url('http://tvh.example:80/tvh') == 'http://tvh.example:80/tvh'
    assert http_base_url('https://tvh.example/tvh') == 'https://tvh.example/tvh'
    assert http_base_url('http://[::1]') == 'http://[::1]:9981'
    assert htsp_host_port('http://tvh.example') == ('tvh.example', 9982)


@pytest.mark.parametrize('url, expected', [
    ('http://tvh.example', 'http://tvh.example:80'),
    ('http://tvh.example/tvh/', 'http://tvh.example:80/tvh/'),
    ('http://user:pw@tvh.example', 'http://user:pw@tvh.example:80'),
    ('http://tvh.example:', 'http://tvh.example:80'),
    ('http://[::1]', 'http://[::1]:80'),
    ('tvh.example', 'http://tvh.example:80'),
    ('http://tvh.example:9981', 'http://tvh.example:9981'),
    ('https://tvh.example', 'https://tvh.example'),
    ('ftp://tvh.example', 'ftp://tvh.example'),
    ('http://tvh.example:abc', 'http://tvh.example:abc'),
    ('http://[host]', 'http://[host]'),
    ('HTTP://tvh.example', 'http://tvh.example:80'),
    ('', ''),
])
def test_pin_http_port_keeps_the_old_port_80_default(url, expected):
    assert pin_http_port(url) == expected


def test_unsupported_scheme_is_rejected():
    with pytest.raises(ValueError, match='Use http:// or https://'):
        http_base_url('ftp://myserver')


@pytest.mark.parametrize('address', [
    'myserver?x=1', 'http://host#frag', 'host?', 'host#',
    'http://[::1', 'http://[::1]oops', 'http://host:',
    'http://[::1]:abc', 'http://[::1]:65536', 'http://host:0',
])
def test_invalid_server_addresses_are_rejected(address):
    with pytest.raises(ValueError):
        http_base_url(address)


def test_ipv6_credentials_preserve_brackets():
    url = insert_basic_auth('http://[::1]:9981/stream/channel/abc', 'user', 'secret')
    assert url == 'http://user:secret@[::1]:9981/stream/channel/abc'
    assert urlparse(url).hostname == '::1'
    assert urlparse(url).port == 9981


def test_insert_basic_auth():
    url = insert_basic_auth('http://127.0.0.1:9981/stream/channel/abc', 'user', 'secret')
    assert url == 'http://user:secret@127.0.0.1:9981/stream/channel/abc'


def test_insert_basic_auth_encodes_special_characters():
    url = insert_basic_auth('http://127.0.0.1:9981/stream/channel/abc', 'a@b.com', 'p@ss/w:rd #?%')
    parsed = urlparse(url)
    assert parsed.hostname == '127.0.0.1'
    assert parsed.port == 9981
    assert parsed.path == '/stream/channel/abc'
    assert unquote(parsed.username) == 'a@b.com'
    assert unquote(parsed.password) == 'p@ss/w:rd #?%'
    assert 'p@ss' not in sanitize(url)


def test_http_auth_none_when_empty():
    assert http_auth({'username': '', 'password': ''}) is None
    auth = http_auth({'username': 'u', 'password': 'secret'})
    assert isinstance(auth, TvhHttpAuth)
    assert auth.username == 'u'
    assert auth.password == 'secret'


def test_http_auth_sends_basic_until_a_digest_nonce_is_known():
    auth = http_auth({'username': 'u', 'password': 'secret'})
    prepared = Request('GET', 'http://127.0.0.1:9981/api/serverinfo').prepare()
    auth(prepared)
    encoded = base64.b64encode(b'u:secret').decode('ascii')
    assert prepared.headers['Authorization'] == f'Basic {encoded}'
