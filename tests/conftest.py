import os

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


@pytest.fixture(scope='session', autouse=True)
def qapp():
    """One QApplication for the whole run.

    Tests get the application with ``QApplication.instance() or QApplication([])``
    and keep it only in a local. Without this reference it was destroyed at the
    end of each test, taking that test's windows with it, while Python still held
    wrappers of their menus. The next application could put new menus at the same
    addresses, PyQt handed back the stale wrappers, and the run crashed at random.
    """
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def pytest_addoption(parser):
    parser.addoption(
        '--run-slow', action='store_true', default=False,
        help='also run the slow tests that start a real Tvheadend server',
    )


def pytest_configure(config):
    config.addinivalue_line(
        'markers', 'slow: starts a real Tvheadend server; runs only with --run-slow, best on its own',
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption('--run-slow'):
        return
    skip = pytest.mark.skip(reason='slow: run with --run-slow')
    for item in items:
        if 'slow' in item.keywords:
            item.add_marker(skip)
