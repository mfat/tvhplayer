"""Set Up Channels: the first-run wizard for a TV tuner or an IPTV playlist.

A tuner is set up here: pick the tuners and the region, then the server scans
and makes channels of what it finds. An IPTV playlist goes on to the Import
Playlist window. Server calls run off the UI thread; ``core.tuner_setup``
holds the steps.
"""

from __future__ import annotations

import threading
import time

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

try:
    from .a11y import announce_label, describe
    from .core.errors import TvhAuthError
    from .core.tuner_setup import (
        KIND_WORDS,
        create_tuner_network,
        discover_satip,
        map_services,
        mapper_progress,
        network_name,
        scan_progress,
        scan_regions,
        services_to_map,
        supported,
    )
    from .core.tuners import read_tuners
    from .core.tvh_admin import TvhAdmin
except ImportError:
    from a11y import announce_label, describe
    from core.errors import TvhAuthError
    from core.tuner_setup import (
        KIND_WORDS,
        create_tuner_network,
        discover_satip,
        map_services,
        mapper_progress,
        network_name,
        scan_progress,
        scan_regions,
        services_to_map,
        supported,
    )
    from core.tuners import read_tuners
    from core.tvh_admin import TvhAdmin

SOURCE_TUNER = 'tuner'
SOURCE_IPTV = 'iptv'
POLL_MS = 2000
# A scan that finds nothing new for this long has stalled.
SCAN_STALL_SECONDS = 600
# SAT>IP servers answer discovery within a few seconds. The server looks for HDHomeRun
# tuners by itself every 15 seconds.
DISCOVERY_WAIT_SECONDS = 4


class ServerCall(QObject):
    """Run ``fn(admin)`` off the UI thread. ``done`` carries the result, or an error message."""

    done = pyqtSignal(object, str)

    def __init__(self, server, fn, parent=None):
        super().__init__(parent)
        self._server = dict(server)
        self._fn = fn
        threading.Thread(target=self._run, name='setup-call', daemon=True).start()

    def _run(self):
        result, error = None, ''
        try:
            with TvhAdmin(self._server) as admin:
                result = self._fn(admin)
        except TvhAuthError:
            error = "This server's login is not allowed to change its settings."
        except Exception as exc:
            error = str(exc) or type(exc).__name__
        try:
            self.done.emit(result, error)
        except RuntimeError:
            pass


class SetupWizard(QWizard):
    """``server`` is a ready server entry; ``on_iptv`` opens the playlist import, ``on_done`` reloads channels."""

    def __init__(self, server, on_iptv, on_done, parent=None):
        super().__init__(parent)
        self.server = dict(server)
        self.on_iptv = on_iptv
        self.on_done = on_done
        self.calls = []
        self.tuners = []
        self.setWindowTitle('Set Up Channels')
        self.setAccessibleName('Set Up Channels')
        self.setWizardStyle(QWizard.WizardStyle.ClassicStyle)
        self.setOption(QWizard.WizardOption.NoBackButtonOnLastPage, True)
        self.setMinimumSize(560, 460)
        self.source_page = SourcePage(self)
        self.tuner_page = TunerPage(self)
        self.scan_page = ScanPage(self)
        self.addPage(self.source_page)
        self.addPage(self.tuner_page)
        self.addPage(self.scan_page)
        self.finished.connect(self._finished)

    def call(self, fn, slot):
        call = ServerCall(self.server, fn, self)
        self.calls.append(call)

        def done(result, error, call=call):
            if call in self.calls:
                self.calls.remove(call)
            slot(result, error)

        call.done.connect(done)
        return call

    def _finished(self, result):
        if result == QWizard.DialogCode.Accepted and self.source_page.choice() == SOURCE_IPTV:
            self.on_iptv(self.server)
        elif self.scan_page.added:
            self.on_done(self.server)


class SourcePage(QWizardPage):
    def __init__(self, wizard):
        super().__init__()
        self._wizard = wizard
        self.setTitle('How do you get TV?')
        self.setSubTitle(f"TVHplayer adds the channels to {wizard.server.get('name') or 'the server'}.")
        layout = QVBoxLayout(self)
        self.group = QButtonGroup(self)
        self.tuner_radio = QRadioButton('A &TV tuner, with an aerial, cable, or satellite dish')
        self.iptv_radio = QRadioButton('An &IPTV playlist: a web address or file ending in .m3u')
        for button in (self.tuner_radio, self.iptv_radio):
            self.group.addButton(button)
            layout.addWidget(button)
            button.toggled.connect(self._changed)
        self.status = QLabel('Looking for tuners…')
        self.status.setWordWrap(True)
        self.status.setContentsMargins(24, 8, 0, 0)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        row.setContentsMargins(24, 0, 0, 0)
        self.look_btn = QPushButton('&Look Again')
        describe(self.look_btn, 'Look Again', 'Look for tuners again, including SAT>IP and HDHomeRun tuners on the network.')
        self.look_btn.clicked.connect(self.look_again)
        row.addWidget(self.look_btn)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(1)
        self._looking = False
        self._looked = False

    def initializePage(self):
        if not self._looked:
            self._read_tuners()

    def look_again(self):
        if self._looking:
            return
        self._looking = True
        self.look_btn.setEnabled(False)
        announce_label(self.status, 'Looking for tuners, including SAT>IP and HDHomeRun tuners on the network…')

        def discover(admin):
            try:
                discover_satip(admin)
                time.sleep(DISCOVERY_WAIT_SECONDS)
            except Exception:
                pass  # A build without SAT>IP still lists its own tuners.
            return read_tuners(admin)

        self._wizard.call(discover, self._tuners_read)

    def _read_tuners(self):
        self._looking = True
        self.look_btn.setEnabled(False)
        self._wizard.call(read_tuners, self._tuners_read)

    def _tuners_read(self, tuners, error):
        self._looking = False
        self._looked = True
        self.look_btn.setEnabled(True)
        if error:
            self._wizard.tuners = []
            announce_label(self.status, f'Could not look for tuners: {error}')
        else:
            self._wizard.tuners = [tuner for tuner in tuners or [] if supported(tuner.kind)]
            found = self._wizard.tuners
            if found:
                names = ', '.join(f'{tuner.name} ({tuner.kind})' for tuner in found)
                announce_label(self.status, f'Found: {names}.')
            elif tuners:
                kinds = ', '.join(sorted({tuner.kind for tuner in tuners}))
                announce_label(self.status, f'Found tuners for {kinds}, which TVHplayer cannot set up yet.')
            else:
                announce_label(
                    self.status,
                    'No tuner found. Plug in a USB tuner, or turn on a SAT>IP or HDHomeRun tuner on this '
                    'network, then choose Look Again.',
                )
        self.tuner_radio.setEnabled(bool(self._wizard.tuners))
        if self.group.checkedButton() is None or not self._wizard.tuners:
            (self.tuner_radio if self._wizard.tuners else self.iptv_radio).setChecked(True)
        self._changed()

    def _changed(self, *_args):
        iptv = self.iptv_radio.isChecked()
        self.setFinalPage(iptv)
        self.setButtonText(QWizard.WizardButton.FinishButton, 'Continue')
        self.completeChanged.emit()

    def choice(self):
        if self.iptv_radio.isChecked():
            return SOURCE_IPTV
        if self.tuner_radio.isChecked():
            return SOURCE_TUNER
        return ''

    def isComplete(self):
        if self.iptv_radio.isChecked():
            return True
        return self.tuner_radio.isChecked() and bool(self._wizard.tuners)

    def nextId(self):
        if self.iptv_radio.isChecked():
            return -1
        return super().nextId()


class TunerPage(QWizardPage):
    def __init__(self, wizard):
        super().__init__()
        self._wizard = wizard
        self._regions = []
        self.setTitle('Choose the tuners and your region')
        self.setSubTitle('The server scans the frequencies used where you live.')
        # Scanning changes the server; there is no going back from it.
        self.setCommitPage(True)
        self.setButtonText(QWizard.WizardButton.CommitButton, '&Scan')
        layout = QVBoxLayout(self)
        kind_row = QHBoxLayout()
        kind_label = QLabel('&Signal:')
        self.kind_combo = QComboBox()
        kind_label.setBuddy(self.kind_combo)
        kind_row.addWidget(kind_label)
        kind_row.addWidget(self.kind_combo, 1)
        layout.addLayout(kind_row)
        tuner_label = QLabel('T&uners to use:')
        self.tuner_list = QListWidget()
        self.tuner_list.setAccessibleName('Tuners to use')
        self.tuner_list.setMaximumHeight(90)
        tuner_label.setBuddy(self.tuner_list)
        layout.addWidget(tuner_label)
        layout.addWidget(self.tuner_list)
        region_label = QLabel('&Region or satellite:')
        self.region_filter = QLineEdit()
        self.region_filter.setPlaceholderText('Type to narrow the list, such as a country or city')
        self.region_filter.setClearButtonEnabled(True)
        describe(self.region_filter, 'Find region', 'Narrows the list of regions below.')
        region_label.setBuddy(self.region_filter)
        self.region_list = QListWidget()
        self.region_list.setAccessibleName('Regions')
        layout.addWidget(region_label)
        layout.addWidget(self.region_filter)
        layout.addWidget(self.region_list, 1)
        self.region_status = QLabel('')
        self.region_status.setWordWrap(True)
        layout.addWidget(self.region_status)
        self.encrypted_check = QCheckBox('Also add &encrypted channels (they need a subscription card)')
        layout.addWidget(self.encrypted_check)
        self.kind_combo.currentIndexChanged.connect(self._kind_changed)
        self.tuner_list.itemChanged.connect(lambda _item: self.completeChanged.emit())
        self.region_filter.textChanged.connect(self._fill_regions)
        self.region_list.currentItemChanged.connect(lambda *_args: self.completeChanged.emit())

    def initializePage(self):
        self.kind_combo.blockSignals(True)
        self.kind_combo.clear()
        for kind in dict.fromkeys(tuner.kind for tuner in self._wizard.tuners):
            self.kind_combo.addItem(KIND_WORDS.get(kind, kind), kind)
        self.kind_combo.blockSignals(False)
        self._kind_changed()

    def kind(self):
        return self.kind_combo.currentData() or ''

    def _kind_changed(self, *_args):
        kind = self.kind()
        self.tuner_list.clear()
        for tuner in self._wizard.tuners:
            if tuner.kind != kind:
                continue
            label = tuner.name if not tuner.hardware else f'{tuner.name} on {tuner.hardware}'
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, tuner)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self.tuner_list.addItem(item)
        self._regions = []
        self.region_list.clear()
        if not kind:
            return
        announce_label(self.region_status, 'Reading the list of regions…')
        self._wizard.call(lambda admin: scan_regions(admin, kind), lambda regions, error: self._regions_read(kind, regions, error))

    def _regions_read(self, kind, regions, error):
        if kind != self.kind():
            return
        if error:
            announce_label(self.region_status, f'Could not read the regions: {error}')
            return
        self._regions = regions or []
        self.region_status.setText('' if self._regions else 'The server has no scan tables for this signal.')
        self._fill_regions()

    def _fill_regions(self, *_args):
        words = self.region_filter.text().lower().split()
        current = self.region()
        self.region_list.clear()
        for key, label in self._regions:
            if all(word in label.lower() for word in words):
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, key)
                self.region_list.addItem(item)
                if key == (current or ('', ''))[0]:
                    self.region_list.setCurrentItem(item)
        self.completeChanged.emit()

    def region(self):
        item = self.region_list.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole), item.text()

    def chosen_tuners(self):
        return [
            self.tuner_list.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(self.tuner_list.count())
            if self.tuner_list.item(row).checkState() == Qt.CheckState.Checked
        ]

    def isComplete(self):
        return bool(self.chosen_tuners()) and self.region() is not None


class ScanPage(QWizardPage):
    def __init__(self, wizard):
        super().__init__()
        self._wizard = wizard
        self.added = 0
        self._network = ''
        self._finished = False
        self._best = (0, 0)
        self._last_change = 0.0
        self.setTitle('Scanning')
        self.setSubTitle('This takes a few minutes. You can keep watching other channels meanwhile.')
        layout = QVBoxLayout(self)
        self.status = QLabel('')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setAccessibleName('Scan progress')
        layout.addWidget(self.progress)
        layout.addStretch(1)
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._poll)
        self._polling = False
        self._step = ''

    def initializePage(self):
        page = self._wizard.tuner_page
        kind = page.kind()
        key, label = page.region()
        tuners = page.chosen_tuners()
        self._include_encrypted = page.encrypted_check.isChecked()
        self._step = 'create'
        self.progress.setRange(0, 0)
        announce_label(self.status, 'Setting up the tuners…')
        self._wizard.call(
            lambda admin: create_tuner_network(admin, kind, key, network_name(kind, label), tuners),
            self._created,
        )

    def _created(self, network, error):
        if error:
            self._fail(f'Could not set up the tuners: {error}')
            return
        self._network = network
        self._step = 'scan'
        self._last_change = time.monotonic()
        announce_label(self.status, 'Scanning frequencies…')
        self._timer.start()

    def _poll(self):
        if self._polling:
            return
        self._polling = True
        if self._step == 'scan':
            network = self._network
            self._wizard.call(lambda admin: scan_progress(admin, network), self._scanned)
        elif self._step == 'map':
            self._wizard.call(mapper_progress, self._mapped)
        else:
            self._polling = False

    def _scanned(self, progress, error):
        self._polling = False
        if error or progress is None:
            self._fail(f'Could not follow the scan: {error}')
            return
        if (progress.scanned, progress.services) != self._best:
            self._best = (progress.scanned, progress.services)
            self._last_change = time.monotonic()
        self.progress.setRange(0, max(progress.muxes, 1))
        self.progress.setValue(progress.scanned)
        services = '1 channel' if progress.services == 1 else f'{progress.services} channels'
        self.status.setText(
            f'Scanned {progress.scanned} of {progress.muxes} frequencies. Found {services} so far.'
        )
        if progress.done or time.monotonic() - self._last_change > SCAN_STALL_SECONDS:
            self._timer.stop()
            self._step = 'list'
            include = self._include_encrypted
            network = self._network
            self._wizard.call(lambda admin: services_to_map(admin, network, include), self._listed)

    def _listed(self, services, error):
        if error:
            self._fail(f'Could not read the channels found: {error}')
            return
        services = services or []
        if not services:
            self._finish(
                'No channels were found. Check that the aerial, cable, or dish is connected to the tuner, '
                'or run Set Up Channels again with another region.'
            )
            return
        self._expected = len(services)
        self._step = 'map'
        announce_label(self.status, f'Adding {len(services)} channels…')
        self.progress.setRange(0, len(services))
        self.progress.setValue(0)
        self._wizard.call(lambda admin: map_services(admin, services), self._map_started)

    def _map_started(self, _result, error):
        if error:
            self._fail(f'Could not add the channels: {error}')
            return
        self._timer.start()

    def _mapped(self, counts, error):
        self._polling = False
        if error or counts is None:
            self._fail(f'Could not follow the channels being added: {error}')
            return
        handled, total = counts
        self.progress.setValue(min(handled, self.progress.maximum()))
        if total and handled < total:
            return
        self._timer.stop()
        self.added = self._expected
        channels = '1 channel' if self.added == 1 else f'{self.added} channels'
        self._finish(
            f'Added {channels}. The TV guide fills in over the next minutes as the channels broadcast it.'
        )

    def _fail(self, text):
        self._timer.stop()
        self._finish(text)

    def _finish(self, text):
        self._step = 'done'
        self._finished = True
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        announce_label(self.status, text)
        self.completeChanged.emit()

    def isComplete(self):
        return self._finished

    def cleanupPage(self):
        self._timer.stop()
