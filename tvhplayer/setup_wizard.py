"""Set Up Channels: the first-run wizard for a TV tuner or an IPTV playlist.

A tuner is set up here: pick the tuners and the region, then the server scans
and makes channels of what it finds. An IPTV playlist goes on to the Import
Playlist window. Server calls run off the UI thread; ``core.tuner_setup``
holds the steps.
"""

from __future__ import annotations

import threading
import time

from PyQt6.QtCore import QEvent, QObject, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QPainter, QPalette, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QStyle,
    QStyleOptionButton,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

try:
    from .a11y import announce_label, describe
    from .ui_theme import color as theme_color, is_active as theme_is_active, is_organic
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
    from ui_theme import color as theme_color, is_active as theme_is_active, is_organic
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


def _is_under(widget, ancestor):
    while widget is not None:
        if widget is ancestor:
            return True
        widget = widget.parentWidget()
    return False


def _title_font(label):
    """A demibold heading when a Qt style is in use. The TVHplayer theme sets its own."""
    if theme_is_active():
        return
    font = QFont(QApplication.font())
    font.setWeight(QFont.Weight.DemiBold)
    font.setPointSizeF(font.pointSizeF() * 1.35)
    label.setFont(font)


class _Title(QLabel):
    def __init__(self, text):
        super().__init__(text)
        self.setObjectName('pageTitle')
        self.setAccessibleName(text)
        _title_font(self)

    def changeEvent(self, event):
        if event.type() == QEvent.Type.StyleChange:
            _title_font(self)
        super().changeEvent(event)


def _heading(layout, title, subtitle):
    heading = _Title(title)
    intro = QLabel(subtitle)
    intro.setObjectName('pageIntro')
    intro.setWordWrap(True)
    layout.addWidget(heading)
    layout.addSpacing(2)
    layout.addWidget(intro)
    return heading


def _section_font(label):
    """Bold section names when a Qt style is in use. The TVHplayer theme sets its own."""
    if theme_is_active():
        return
    font = QFont(QApplication.font())
    font.setWeight(QFont.Weight.DemiBold)
    label.setFont(font)


class _Section(QLabel):
    def __init__(self, text, buddy=None):
        super().__init__(text)
        self.setObjectName('groupTitle')
        if buddy is not None:
            self.setBuddy(buddy)
        _section_font(self)

    def changeEvent(self, event):
        if event.type() == QEvent.Type.StyleChange:
            _section_font(self)
        super().changeEvent(event)


def _tuner_detail(tuner):
    """Where the tuner is, and what it receives, when the name does not already say so."""
    parts = []
    name = tuner.name or ''
    hardware = (tuner.hardware or '').strip()
    if hardware and hardware not in name:
        parts.append(hardware)
    if tuner.kind and tuner.kind not in name:
        parts.append(tuner.kind)
    return ' · '.join(parts)


class _TunerRow(QWidget):
    """One found tuner: its name, then where it is and what it receives."""

    def __init__(self, tuner):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        name = QLabel(tuner.name)
        name.setObjectName('rowTitle')
        name.setWordWrap(True)
        detail = QLabel(_tuner_detail(tuner))
        detail.setObjectName('rowDesc')
        detail.setWordWrap(True)
        if not detail.text():
            detail.hide()
        layout.addWidget(name)
        layout.addWidget(detail)
        self.setAccessibleName(f'{tuner.name} ({tuner.kind})' if tuner.kind else tuner.name)


class ChoiceCard(QFrame):
    """A radio option drawn as a card. Clicking the card selects it."""

    def __init__(self, radio, detail):
        super().__init__()
        self.radio = radio
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(4)
        self._detail = QLabel(detail)
        self._detail.setObjectName('rowDesc')
        self._detail.setWordWrap(True)
        layout.addWidget(radio)
        layout.addWidget(self._detail)
        self.body = QVBoxLayout()
        self.body.setSpacing(8)
        layout.addLayout(self.body)
        radio.toggled.connect(self.update)
        radio.installEventFilter(self)
        self._restyle()
        self._align()
        self._sync_cursor()

    def changeEvent(self, event):
        if event.type() == QEvent.Type.StyleChange:
            self._restyle()
            self._align()
        super().changeEvent(event)

    def showEvent(self, event):
        self._align()
        super().showEvent(event)

    def _align(self):
        """The note and the tuner list start where the radio's text does."""
        option = QStyleOptionButton()
        self.radio.initStyleOption(option)
        indent = self.style().subElementRect(QStyle.SubElement.SE_RadioButtonContents, option, self.radio).x()
        if indent <= 0:
            return
        self._detail.setContentsMargins(indent, 0, 0, 0)
        self.body.setContentsMargins(indent, 8, 0, 0)

    def eventFilter(self, watched, event):
        if watched is self.radio and event.type() == QEvent.Type.EnabledChange:
            self._sync_cursor()
            self.update()
        return super().eventFilter(watched, event)

    def _restyle(self):
        self.setFrameShape(QFrame.Shape.NoFrame if theme_is_active() else QFrame.Shape.StyledPanel)

    def _sync_cursor(self):
        cursor = Qt.CursorShape.PointingHandCursor if self.radio.isEnabled() else Qt.CursorShape.ArrowCursor
        self.setCursor(cursor)

    def _selected(self):
        return self.radio.isEnabled() and self.radio.isChecked()

    def mousePressEvent(self, event):
        if self.radio.isEnabled() and event.button() == Qt.MouseButton.LeftButton:
            self.radio.setChecked(True)
            self.radio.setFocus(Qt.FocusReason.MouseFocusReason)
        super().mousePressEvent(event)

    def paintEvent(self, event):
        if not theme_is_active():
            super().paintEvent(event)
            if not self._selected():
                return
            self._stroke(self.palette().color(QPalette.ColorRole.Highlight), 6, 2)
            return
        selected = self._selected()
        width = 2 if selected else 1
        radius = 14 if is_organic() else 8
        self._stroke(theme_color('accent' if selected else 'edge_soft'), radius, width, theme_color('base'))

    def _stroke(self, edge, radius, width, fill=None):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(width / 2, width / 2, -width / 2, -width / 2)
        painter.setPen(QPen(edge, width))
        painter.setBrush(fill if fill is not None else Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, max(0, radius - width / 2), max(0, radius - width / 2))


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
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)
        self.setOption(QWizard.WizardOption.NoBackButtonOnLastPage, True)
        self.setOption(QWizard.WizardOption.CancelButtonOnLeft, True)
        self.setMinimumSize(600, 520)
        self.setButtonText(QWizard.WizardButton.BackButton, '&Back')
        self.setButtonText(QWizard.WizardButton.NextButton, '&Next')
        self.setButtonText(QWizard.WizardButton.CancelButton, 'Cancel')
        for which in (
            QWizard.WizardButton.NextButton,
            QWizard.WizardButton.CommitButton,
            QWizard.WizardButton.FinishButton,
        ):
            self.button(which).setProperty('primary', True)
        self.currentIdChanged.connect(lambda _page: QTimer.singleShot(0, self._tuck_header))
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

    def showEvent(self, event):
        super().showEvent(event)
        self._tuck_header()
        QTimer.singleShot(0, self._tuck_header)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.StyleChange:
            QTimer.singleShot(0, self._tuck_header)

    def _tuck_header(self):
        """The classic wizard heading is a small bold line. Each page draws its own."""
        page = self.currentPage()
        title = page.title() if page is not None else ''
        if not title:
            return
        for label in self.findChildren(QLabel):
            if label.text() != title or _is_under(label, page):
                continue
            header = label.parentWidget()
            if header is None:
                continue
            header.hide()
            header.setMaximumHeight(0)
            return


class SourcePage(QWizardPage):
    def __init__(self, wizard):
        super().__init__()
        self._wizard = wizard
        server = wizard.server.get('name') or 'the server'
        self.setTitle('How do you get TV?')
        self.setSubTitle(f'Channels are added to {server}.')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 16, 8, 8)
        layout.setSpacing(14)
        _heading(layout, self.title(), self.subTitle())
        self.group = QButtonGroup(self)
        self.tuner_radio = QRadioButton('&TV tuner')
        self.iptv_radio = QRadioButton('&IPTV playlist')
        describe(self.tuner_radio, 'TV tuner', 'An aerial, cable, or a satellite dish.')
        describe(self.iptv_radio, 'IPTV playlist', 'A web address or a file ending in .m3u.')
        self.group.addButton(self.tuner_radio)
        self.group.addButton(self.iptv_radio)
        self.tuner_card = ChoiceCard(self.tuner_radio, 'An aerial, cable, or a satellite dish.')
        self.iptv_card = ChoiceCard(self.iptv_radio, 'A web address or a file ending in .m3u.')
        self.status = QLabel('Looking for tuners…')
        self.status.setWordWrap(True)
        self.found = QWidget()
        self._found_rows = QVBoxLayout(self.found)
        self._found_rows.setContentsMargins(0, 0, 0, 0)
        self._found_rows.setSpacing(10)
        self.found.hide()
        self.look_btn = QPushButton('&Look again')
        describe(self.look_btn, 'Look again', 'Look for tuners again, including SAT>IP and HDHomeRun tuners on the network.')
        self.look_btn.clicked.connect(self.look_again)
        actions = QHBoxLayout()
        actions.addWidget(self.look_btn)
        actions.addStretch(1)
        self.tuner_card.body.addWidget(self.status)
        self.tuner_card.body.addWidget(self.found)
        self.tuner_card.body.addLayout(actions)
        layout.addWidget(self.tuner_card)
        layout.addWidget(self.iptv_card)
        layout.addStretch(1)
        self.tuner_radio.toggled.connect(self._changed)
        self.iptv_radio.toggled.connect(self._changed)
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
        # Show the line first: a hidden label is not announced.
        self._show_found([])
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
                    'network, then choose Look again.',
                )
        self._show_found(self._wizard.tuners)
        self.tuner_radio.setEnabled(bool(self._wizard.tuners))
        if self.group.checkedButton() is None or not self._wizard.tuners:
            (self.tuner_radio if self._wizard.tuners else self.iptv_radio).setChecked(True)
        self._changed()

    def _show_found(self, tuners):
        while self._found_rows.count():
            item = self._found_rows.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        for tuner in tuners or []:
            self._found_rows.addWidget(_TunerRow(tuner))
        self.found.setVisible(bool(tuners))
        # The sentence stays for assistive technology. The rows say the same thing on screen.
        self.status.setVisible(not tuners)

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
        layout.setContentsMargins(8, 16, 8, 8)
        layout.setSpacing(4)
        _heading(layout, self.title(), self.subTitle())
        layout.addSpacing(10)
        self.kind_combo = QComboBox()
        kind_label = _Section('&Signal', self.kind_combo)
        self.tuner_list = QListWidget()
        self.tuner_list.setAccessibleName('Tuners to use')
        self.tuner_list.setMaximumHeight(140)
        tuner_label = _Section('T&uners to use', self.tuner_list)
        self.region_filter = QLineEdit()
        self.region_filter.setPlaceholderText('Type to narrow the list, such as a country or city')
        self.region_filter.setClearButtonEnabled(True)
        describe(self.region_filter, 'Find region', 'Narrows the list of regions below.')
        region_label = _Section('&Region or satellite', self.region_filter)
        self.region_list = QListWidget()
        self.region_list.setAccessibleName('Regions')
        self.region_status = QLabel('')
        self.region_status.setWordWrap(True)
        self.region_status.setObjectName('rowDesc')
        self.region_status.hide()
        self.encrypted_check = QCheckBox('Also add &encrypted channels (they need a subscription card)')
        for index, (label, widget) in enumerate((
            (kind_label, self.kind_combo),
            (tuner_label, self.tuner_list),
            (region_label, self.region_filter),
        )):
            if index:
                layout.addSpacing(12)
            layout.addWidget(label)
            layout.addWidget(widget)
        layout.addWidget(self.region_list, 1)
        layout.addWidget(self.region_status)
        layout.addSpacing(6)
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
        self.region_status.show()
        self._wizard.call(lambda admin: scan_regions(admin, kind), lambda regions, error: self._regions_read(kind, regions, error))

    def _regions_read(self, kind, regions, error):
        if kind != self.kind():
            return
        if error:
            announce_label(self.region_status, f'Could not read the regions: {error}')
            self.region_status.show()
            return
        self._regions = regions or []
        self.region_status.setText('' if self._regions else 'The server has no scan tables for this signal.')
        self.region_status.setVisible(bool(self.region_status.text()))
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
        layout.setContentsMargins(8, 16, 8, 8)
        layout.setSpacing(14)
        _heading(layout, self.title(), self.subTitle())
        self._card = QFrame()
        self._card.setObjectName('groupCard')
        self._restyle_card()
        card = self._card
        inner = QVBoxLayout(card)
        inner.setContentsMargins(18, 16, 18, 16)
        inner.setSpacing(14)
        self.status = QLabel('')
        self.status.setWordWrap(True)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setAccessibleName('Scan progress')
        inner.addWidget(self.status)
        inner.addWidget(self.progress)
        layout.addWidget(card)
        layout.addStretch(1)
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._poll)
        self._polling = False
        self._step = ''

    def changeEvent(self, event):
        if event.type() == QEvent.Type.StyleChange:
            self._restyle_card()
        super().changeEvent(event)

    def _restyle_card(self):
        self._card.setFrameShape(QFrame.Shape.NoFrame if theme_is_active() else QFrame.Shape.StyledPanel)

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
