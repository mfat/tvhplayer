"""The Settings window: playback at startup, where recordings go, and imported channels that do not work.

Layout: a sidebar of five pages (Playback, Channels, Recordings, Conversion, Sleep). Every setting is a
row with its name and description on the left and the control on the right. The settings logic and
the widget attribute names are unchanged from the tabbed version.
"""

from __future__ import annotations

import sys

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

try:
    from .a11y import announce_label, describe
    from .core.recorder import RECORDING_FORMATS, parse_ffmpeg_options
    from .core.engine import ENGINE_AUTO, ENGINE_MPV, ENGINE_VLC, choose_engine
    from .settings_widgets import SettingRow, SettingsGroup, SettingsNav, SettingsPage, StatusStrip, ToggleSwitch
except ImportError:
    from a11y import announce_label, describe
    from core.recorder import RECORDING_FORMATS, parse_ffmpeg_options
    from core.engine import ENGINE_AUTO, ENGINE_MPV, ENGINE_VLC, choose_engine
    from settings_widgets import SettingRow, SettingsGroup, SettingsNav, SettingsPage, StatusStrip, ToggleSwitch

HIDE_HELP = (
    'After an import or refresh, the server tests each channel in the background. '
    'Channels that fail are hidden and come back once a later test finds them working.'
)
PLAY_HELP = 'Once the channel list has loaded, the channel you watched last starts playing.'
ENGINE_HELP = (
    'Automatic plays with mpv when the desktop uses Wayland and with VLC on X11. '
    'With VLC on a Wayland desktop, the whole window runs through XWayland and can look soft when scaled. '
    'A change takes effect the next time TVHplayer starts.'
)
ENGINE_SHORT = 'Automatic plays with mpv when the desktop uses Wayland and with VLC on X11.'
ENGINE_NOTE = (
    'With VLC on a Wayland desktop, the whole window runs through XWayland and can look soft when scaled. '
    'A change takes effect the next time TVHplayer starts.'
)
ENGINE_NAMES = {ENGINE_MPV: 'mpv', ENGINE_VLC: 'VLC'}
FOLDER_HELP = 'Recording to this computer saves here without asking for a file name.'
BUILTIN_FOLDER_HELP = ' The built-in server saves its recordings here too.'
OPTIONS_HELP = (
    'Added after the format\'s own ffmpeg output options, so they override them, '
    'for example -c:a aac -b:a 128k. Leave empty for the defaults.'
)
CONVERT_HELP = (
    'Makes an MP4 next to each new recording with a constant frame rate and a keyframe every second, '
    'so video editors seek through it smoothly. The frame rate is taken from the recording; '
    'the options choose the encoder and quality. Any recording can also be converted by '
    'right-clicking it in Tasks.'
)
CONVERT_INTRO = (
    'Makes an MP4 next to each new recording with a constant frame rate and a keyframe every second, '
    'so video editors seek through it smoothly. Any recording can also be converted by right-clicking it in Tasks.'
)
AWAKE_HELP = (
    'The computer never sleeps while it is recording. With this on, it also stays awake while a '
    'recording is scheduled on the built-in server or another server on this computer, so the '
    'recording is not missed. TVHplayer has to be open for the built-in server to record.'
)
PADDING_HELP = (
    'The built-in server starts each recording this many minutes before the programme and '
    'keeps recording this long after it, in case the broadcast runs early or late.'
)
SPACE_HELP = 'The status bar warns when the recordings folder has less space than this. 0 turns the warning off.'
PICON_HELP = (
    'Picons are channel logos collected by the picons project. TVHplayer shows one for each channel '
    'the server has no logo for, matched by the channel name. The pack is about 25 MB.'
)
LOGOS_HELP = "Each channel's logo is shown next to its name in the channel list and the guide."
CHECK_HELP = 'Test every imported channel now and hide the ones that do not work.'
DELETE_HELP = 'Only after a successful conversion. Recordings converted by hand are always kept.'


class SettingsDialog(QDialog):
    """``host`` is the main window: it keeps the setting and runs the checks."""

    PAGES = (
        ('Playback', 'Startup, engine'),
        ('Channels', 'Logos, imported playlists'),
        ('Recordings', 'Folder, format, padding'),
        ('Conversion', 'Edit-friendly copies'),
        ('Sleep', 'Scheduled recordings'),
    )

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self._host = host
        self._jobs = []
        self.setWindowTitle('Settings')
        self.setModal(True)
        self.setAccessibleName('Settings')
        self.setMinimumSize(720, 520)
        self.resize(860, 640)
        has_builtin = getattr(host, 'builtin', None) is not None

        pages = [
            self._playback_page(host),
            self._channels_page(host),
            self._recordings_page(host, has_builtin),
            self._conversion_page(host),
            self._sleep_page(host),
        ]

        self.nav = SettingsNav()
        self.pages = QStackedWidget()
        for (title, subtitle), page in zip(self.PAGES, pages):
            self.nav.add_page(title, subtitle)
            self.pages.addWidget(page)
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav.setCurrentRow(0)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self.nav)
        body.addWidget(self.pages, 1)

        footer = QFrame()
        footer.setObjectName('dialogFooter')
        footer_row = QHBoxLayout(footer)
        footer_row.setContentsMargins(20, 10, 16, 10)
        note = QLabel('Changes are saved as you make them.')
        note.setObjectName('footerNote')
        close = QPushButton('Close')
        close.setDefault(True)
        close.clicked.connect(self.reject)
        footer_row.addWidget(note)
        footer_row.addStretch(1)
        footer_row.addWidget(close)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(body, 1)
        layout.addWidget(footer)

        self.play_check.toggled.connect(host.set_plays_on_start)
        self.folder_btn.clicked.connect(self._choose_folder)
        self.format_combo.currentIndexChanged.connect(self._format_chosen)
        self.options_edit.editingFinished.connect(self._options_edited)
        self.convert_check.toggled.connect(self._convert_toggled)
        self.convert_edit.editingFinished.connect(self._convert_edited)
        self.delete_check.toggled.connect(host.set_deletes_converted_original)
        self.awake_check.toggled.connect(host.set_stays_awake_for_scheduled)
        self.space_spin.editingFinished.connect(self._space_edited)
        self.logos_check.toggled.connect(host.set_shows_channel_logos)
        self.picon_btn.clicked.connect(self._download_picons)
        self.picon_remove_btn.clicked.connect(self._remove_picons)
        self._picon_job = None
        job = getattr(host, 'picon_job', None)
        if job is not None and job.is_download():
            self._follow_picon_job(job)
        self._show_picons()
        self._delete_row.setEnabled(self.convert_check.isChecked())
        self._show_convert_problem(self.convert_edit.text())
        self.hide_check.toggled.connect(self._toggled)
        self.check_btn.clicked.connect(self._check)
        self._sync()

    # Pages ---------------------------------------------------------------

    def _playback_page(self, host):
        page = SettingsPage('Playback')
        startup = page.add(SettingsGroup('Startup'))
        self.play_check = ToggleSwitch('Play the last channel when TVHplayer starts')
        self.play_check.setChecked(host.plays_on_start())
        describe(self.play_check, description=PLAY_HELP)
        startup.add_row(SettingRow('&Play the last channel when TVHplayer starts', PLAY_HELP, self.play_check))

        self.engine_combo = None
        # libmpv is used only on Linux; elsewhere VLC is the only engine.
        if sys.platform.startswith('linux'):
            engine = page.add(SettingsGroup('Playback engine'))
            self.engine_combo = QComboBox()
            self.engine_combo.setMinimumWidth(170)
            for label, choice in (('Automatic', ENGINE_AUTO), ('mpv', ENGINE_MPV), ('VLC', ENGINE_VLC)):
                self.engine_combo.addItem(label, choice)
            self.engine_combo.setCurrentIndex(max(self.engine_combo.findData(host.player_engine_choice()), 0))
            describe(self.engine_combo, 'Playback engine', ENGINE_HELP)
            engine.add_row(SettingRow('Playback &engine', ENGINE_SHORT, self.engine_combo))
            strip = engine.add_strip(StatusStrip())
            self.engine_status = strip.label
            note = QLabel(ENGINE_NOTE)
            note.setObjectName('rowDesc')
            note.setWordWrap(True)
            strip.layout().addWidget(note)
            self._show_engine()
            self.engine_combo.currentIndexChanged.connect(self._engine_chosen)
        page.finish()
        return page

    def _channels_page(self, host):
        page = SettingsPage('Channels')
        logos = page.add(SettingsGroup('Channel logos'))
        self.logos_check = ToggleSwitch('Show channel logos')
        self.logos_check.setChecked(host.shows_channel_logos())
        describe(self.logos_check, description=LOGOS_HELP)
        logos.add_row(SettingRow('Show channel &logos', LOGOS_HELP, self.logos_check))

        buttons = QWidget()
        button_row = QHBoxLayout(buttons)
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(8)
        self.picon_remove_btn = QPushButton('Remo&ve')
        describe(self.picon_remove_btn, 'Remove Picons', 'Delete the downloaded picons.')
        self.picon_btn = QPushButton('&Download Picons')
        self.picon_btn.setProperty('primary', True)
        describe(self.picon_btn, 'Download Picons', PICON_HELP)
        button_row.addWidget(self.picon_remove_btn)
        button_row.addWidget(self.picon_btn)
        logos.add_row(SettingRow('Picons', PICON_HELP, buttons))
        strip = logos.add_strip(StatusStrip(progress=True))
        self._picon_strip = strip
        self.picon_progress = strip.progress
        self.picon_progress.setAccessibleName('Picon download')
        self.picon_status = strip.label

        imported = page.add(SettingsGroup('Imported channels'))
        self.hide_check = ToggleSwitch('Hide channels that do not work')
        self.hide_check.setChecked(host.hides_dead_channels())
        describe(self.hide_check, description=HIDE_HELP)
        imported.add_row(SettingRow('&Hide channels that do not work', HIDE_HELP, self.hide_check))
        self.check_btn = QPushButton('&Check Now')
        describe(self.check_btn, 'Check Channels Now', CHECK_HELP)
        self.check_btn.setToolTip(CHECK_HELP)
        imported.add_row(SettingRow('Check channels now', CHECK_HELP, self.check_btn))
        self.status_label = imported.add_strip(StatusStrip()).label
        page.finish()
        return page

    def _recordings_page(self, host, has_builtin):
        page = SettingsPage('Recordings')
        storage = page.add(SettingsGroup('Storage'))
        folder = QWidget()
        folder_row = QHBoxLayout(folder)
        folder_row.setContentsMargins(0, 0, 0, 0)
        folder_row.setSpacing(8)
        self.folder_edit = QLineEdit(host.local_recording_dir())
        self.folder_edit.setReadOnly(True)
        self.folder_edit.setPlaceholderText('Chosen the first time you record')
        folder_text = FOLDER_HELP + (BUILTIN_FOLDER_HELP if has_builtin else '')
        describe(self.folder_edit, 'Recordings folder', folder_text)
        self.folder_btn = QPushButton('&Browse…')
        describe(self.folder_btn, 'Browse', 'Choose the folder for recordings.')
        folder_row.addWidget(self.folder_edit, 1)
        folder_row.addWidget(self.folder_btn)
        storage.add_row(SettingRow('&Save recordings in', folder_text, folder, stacked=True))
        self.space_spin = QSpinBox()
        self.space_spin.setRange(0, 10000)
        self.space_spin.setSuffix(' GB')
        self.space_spin.setSpecialValueText('Never')
        self.space_spin.setValue(host.low_space_gb())
        self.space_spin.setMinimumWidth(110)
        describe(self.space_spin, 'Warn when free space is below', SPACE_HELP)
        self.space_spin.setToolTip(SPACE_HELP)
        storage.add_row(SettingRow('&Warn when free space is below', SPACE_HELP, self.space_spin))

        fmt = page.add(SettingsGroup('File format'))
        self.format_combo = QComboBox()
        self.format_combo.setMinimumWidth(170)
        for key, (label, _description, _options) in RECORDING_FORMATS.items():
            self.format_combo.addItem(label, key)
        self.format_combo.setCurrentIndex(max(self.format_combo.findData(host.recording_format()), 0))
        describe(self.format_combo, 'Format', 'The file format of recordings to this computer.')
        format_row = fmt.add_row(SettingRow('&Format', ' ', self.format_combo))
        self.format_help = format_row.description
        self._show_format_help()
        self.options_edit = QLineEdit(host.recording_ffmpeg_options())
        self.options_edit.setPlaceholderText('None')
        self.options_edit.setProperty('mono', True)
        describe(self.options_edit, 'Extra ffmpeg options', OPTIONS_HELP)
        self.options_edit.setToolTip(OPTIONS_HELP)
        fmt.add_row(SettingRow('Extra ffmpeg &options', OPTIONS_HELP, self.options_edit, stacked=True))
        self.options_status = fmt.add_strip(StatusStrip()).label

        self.early_spin = self.late_spin = None
        if has_builtin:
            early, late = host.recording_padding()
            padding = page.add(SettingsGroup('Built-in server'))
            early_label = QLabel('Start &early by')
            self.early_spin = self._minutes_spin(early, 'Start recordings early by', early_label)
            padding.add_row(SettingRow(early_label, '', self.early_spin))
            late_label = QLabel('End &late by')
            self.late_spin = self._minutes_spin(late, 'End recordings late by', late_label)
            padding.add_row(SettingRow(late_label, '', self.late_spin))
            padding.add_strip(StatusStrip(PADDING_HELP))
        page.finish()
        return page

    def _conversion_page(self, host):
        page = SettingsPage('Converting for editing', CONVERT_INTRO)
        group = page.add(SettingsGroup())
        self.convert_check = ToggleSwitch('Convert recordings for editing when they finish')
        self.convert_check.setChecked(host.converts_after_recording())
        describe(self.convert_check, description=CONVERT_HELP)
        group.add_row(SettingRow('Con&vert recordings when they finish',
                                 'The frame rate is taken from the recording.', self.convert_check))
        self.convert_edit = QLineEdit(host.convert_options())
        self.convert_edit.setProperty('mono', True)
        describe(self.convert_edit, 'Conversion options', 'ffmpeg options for the edit-friendly copy.')
        group.add_row(SettingRow('Conversion op&tions',
                                 'ffmpeg options for the edit-friendly copy: the encoder and quality. '
                                 'Leave empty to restore the defaults.', self.convert_edit, stacked=True))
        self.delete_check = ToggleSwitch('Delete the original once a new recording is converted')
        self.delete_check.setChecked(host.deletes_converted_original())
        describe(self.delete_check, description=DELETE_HELP)
        self._delete_row = group.add_row(
            SettingRow('&Delete the original once a new recording is converted', DELETE_HELP, self.delete_check))
        self.convert_status = group.add_strip(StatusStrip()).label
        page.finish()
        return page

    def _sleep_page(self, host):
        page = SettingsPage('Sleep')
        group = page.add(SettingsGroup())
        self.awake_check = ToggleSwitch('Keep the computer awake for scheduled recordings')
        self.awake_check.setChecked(host.stays_awake_for_scheduled())
        describe(self.awake_check, description=AWAKE_HELP)
        group.add_row(SettingRow(
            '&Keep the computer awake for scheduled recordings',
            'Also stays awake while a recording is scheduled on the built-in server or another server '
            'on this computer, so the recording is not missed.',
            self.awake_check,
        ))
        group.add_strip(StatusStrip(
            'The computer never sleeps while it is recording. '
            'TVHplayer has to be open for the built-in server to record.'
        ))
        page.finish()
        return page

    # Behaviour (unchanged from the tabbed dialog) --------------------------

    def _engine_chosen(self, _index):
        self._host.set_player_engine_choice(self.engine_combo.currentData())
        self._show_engine(announce=True)

    def _show_engine(self, announce=False):
        running = self._host.engine
        wanted, reason = choose_engine(preference=self.engine_combo.currentData())
        if wanted == running:
            text = f'Playing with {ENGINE_NAMES[running]}.'
        else:
            text = f'Playing with {ENGINE_NAMES[running]}. Restart TVHplayer to play with {ENGINE_NAMES[wanted]}.'
        if wanted == ENGINE_VLC and self.engine_combo.currentData() == ENGINE_MPV:
            text += f' mpv cannot be used: {reason}.'
        if announce:
            announce_label(self.engine_status, text)
        else:
            self.engine_status.setText(text)

    def _show_picons(self, text=None):
        count = self._host.picon_count()
        busy = self._picon_job is not None
        self.picon_btn.setText('Up&date Picons' if count else '&Download Picons')
        self.picon_btn.setEnabled(not busy)
        self.picon_remove_btn.setEnabled(bool(count) and not busy)
        if text is None:
            text = (f'{count:,} picons are ready. Channels without a logo from the server use them.'
                    if count else 'No picons downloaded.')
        announce_label(self.picon_status, text)
        self._picon_strip.refresh()

    def _download_picons(self):
        self._follow_picon_job(self._host.download_picons())

    def _follow_picon_job(self, job):
        self._picon_job = job
        self.picon_progress.setRange(0, 0)
        self.picon_progress.show()
        job.progress.connect(self._picon_progress)
        job.finished.connect(self._picons_done)
        self._show_picons('Downloading picons…')

    def _picon_progress(self, done, total):
        if total:
            self.picon_progress.setRange(0, total)
            self.picon_progress.setValue(min(done, total))
            if done >= total:
                self.picon_progress.setRange(0, 0)
                self.picon_status.setText('Unpacking the picons…')

    def _picons_done(self, _index, error):
        self._picon_job = None
        self.picon_progress.hide()
        self._show_picons(f'Could not download the picons: {error}' if error else None)

    def _remove_picons(self):
        self._host.remove_picons()
        self._show_picons()

    def _minutes_spin(self, value, name, label):
        spin = QSpinBox()
        spin.setRange(0, 240)
        spin.setSuffix(' min')
        spin.setValue(value)
        spin.setMinimumWidth(110)
        describe(spin, name, PADDING_HELP)
        spin.setToolTip(PADDING_HELP)
        label.setBuddy(spin)
        spin.editingFinished.connect(self._padding_edited)
        return spin

    def _padding_edited(self):
        padding = (self.early_spin.value(), self.late_spin.value())
        if padding != tuple(self._host.recording_padding()):
            self._host.set_recording_padding(*padding)

    def _space_edited(self):
        if self.space_spin.value() != self._host.low_space_gb():
            self._host.set_low_space_gb(self.space_spin.value())

    def _choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, 'Recordings Folder', self.folder_edit.text())
        if folder:
            self.folder_edit.setText(folder)
            self._host.set_local_recording_dir(folder)

    def _show_format_help(self):
        description = RECORDING_FORMATS[self.format_combo.currentData()][1]
        self.format_help.setText(description)
        self.format_combo.setAccessibleDescription(description)

    def _format_chosen(self, _index):
        self._show_format_help()
        self._host.set_recording_format(self.format_combo.currentData())

    def _options_edited(self):
        text = self.options_edit.text().strip()
        try:
            parse_ffmpeg_options(text)
        except ValueError as e:
            announce_label(self.options_status, f'These options cannot be read ({e}); they were not saved.')
            return
        self.options_status.setText('')
        if text != self._host.recording_ffmpeg_options():
            self._host.set_recording_ffmpeg_options(text)

    def _convert_toggled(self, on):
        self._host.set_converts_after_recording(on)
        self._delete_row.setEnabled(on)

    def _show_convert_problem(self, text):
        problem = self._host.conversion_problem(text)
        if problem:
            announce_label(self.convert_status, f'{problem} Recordings cannot be converted with these options.')
        else:
            self.convert_status.setText('')
        return problem

    def _convert_edited(self):
        text = self.convert_edit.text().strip()
        if not text:
            # Empty brings back the default options.
            self._host.set_convert_options('')
            self.convert_edit.setText(self._host.convert_options())
            self._show_convert_problem(self.convert_edit.text())
            return
        try:
            parse_ffmpeg_options(text)
        except ValueError as e:
            announce_label(self.convert_status, f'These options cannot be read ({e}); they were not saved.')
            return
        # A missing encoder is shown but the options are kept: it may be installed later.
        self._show_convert_problem(text)
        if text != self._host.convert_options():
            self._host.set_convert_options(text)

    def done(self, result):
        # Closing with an options field focused does not finish editing first.
        self._options_edited()
        self._convert_edited()
        self._space_edited()
        if self.early_spin is not None:
            self._padding_edited()
        super().done(result)

    def _toggled(self, on):
        self._host.set_hides_dead_channels(on)
        if on:
            announce_label(self.status_label, 'Channels that do not work are hidden from the next import or refresh on.')
        else:
            announce_label(self.status_label, 'Hidden channels are shown again. Imports no longer test channels.')

    def _check(self):
        self._jobs = self._host.check_playlist_channels()
        if not self._jobs:
            announce_label(self.status_label, 'There are no imported playlists to check.')
            return
        for job in self._jobs:
            job.finished.connect(lambda *_args: self._sync())
            job.failed.connect(lambda *_args: self._sync())
        count = len(self._jobs)
        playlists = '1 playlist' if count == 1 else f'{count} playlists'
        announce_label(
            self.status_label,
            f'Checking {playlists} in the background. Channels that do not work are hidden as they are found; '
            'the status bar says when it is done.',
        )
        self._sync()

    def _sync(self):
        running = any(job.is_running() for job in self._host.playlist_checks())
        self.check_btn.setEnabled(not running)
        if running:
            self.check_btn.setToolTip('Channels are being checked.')
        else:
            self.check_btn.setToolTip(CHECK_HELP)
