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
