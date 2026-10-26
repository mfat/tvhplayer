"""The Settings window: playback at startup, where recordings go, and imported channels that do not work."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

try:
    from .a11y import announce_label, describe
    from .core.recorder import RECORDING_FORMATS, parse_ffmpeg_options
except ImportError:
    from a11y import announce_label, describe
    from core.recorder import RECORDING_FORMATS, parse_ffmpeg_options

HIDE_HELP = (
    'After an import or refresh, the server tests each channel in the background. '
    'Channels that fail are hidden and come back once a later test finds them working.'
)
PLAY_HELP = 'Once the channel list has loaded, the channel you watched last starts playing.'
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


class SettingsDialog(QDialog):
    """``host`` is the main window: it keeps the setting and runs the checks."""

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self._host = host
        self._jobs = []
        self.setWindowTitle('Settings')
        self.setModal(True)
        self.setMinimumWidth(480)
        self.setAccessibleName('Settings')
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        general_page = QWidget()
        general = QVBoxLayout(general_page)
        recordings_page = QWidget()
        recording_tab = QVBoxLayout(recordings_page)

        playback = QGroupBox('Playback')
        playback_layout = QVBoxLayout(playback)
        self.play_check = QCheckBox('&Play the last channel when TVHplayer starts')
        self.play_check.setChecked(host.plays_on_start())
        describe(self.play_check, description=PLAY_HELP)
        playback_layout.addWidget(self.play_check)
        play_help = QLabel(PLAY_HELP)
        play_help.setWordWrap(True)
        play_help.setContentsMargins(24, 0, 0, 0)
        playback_layout.addWidget(play_help)
        general.addWidget(playback)

        recordings = QGroupBox('Recordings')
        recordings_layout = QVBoxLayout(recordings)
        folder_label = QLabel('&Save recordings in:')
        recordings_layout.addWidget(folder_label)
        folder_row = QHBoxLayout()
        self.folder_edit = QLineEdit(host.local_recording_dir())
        self.folder_edit.setReadOnly(True)
        self.folder_edit.setPlaceholderText('Chosen the first time you record')
        folder_text = FOLDER_HELP + (BUILTIN_FOLDER_HELP if getattr(host, 'builtin', None) is not None else '')
        describe(self.folder_edit, 'Recordings folder', folder_text)
        folder_label.setBuddy(self.folder_edit)
        folder_row.addWidget(self.folder_edit, 1)
        self.folder_btn = QPushButton('&Browse…')
        describe(self.folder_btn, 'Browse', 'Choose the folder for recordings.')
        folder_row.addWidget(self.folder_btn)
        recordings_layout.addLayout(folder_row)
        folder_help = QLabel(folder_text)
        folder_help.setWordWrap(True)
        recordings_layout.addWidget(folder_help)

        form = QGridLayout()
        form.setColumnStretch(1, 1)
        self.format_combo = QComboBox()
        for key, (label, _description, _options) in RECORDING_FORMATS.items():
            self.format_combo.addItem(label, key)
        self.format_combo.setCurrentIndex(max(self.format_combo.findData(host.recording_format()), 0))
        describe(self.format_combo, 'Format', 'The file format of recordings to this computer.')
        format_label = QLabel('&Format:')
        format_label.setBuddy(self.format_combo)
        form.addWidget(format_label, 0, 0)
        form.addWidget(self.format_combo, 0, 1)
        self.options_edit = QLineEdit(host.recording_ffmpeg_options())
        self.options_edit.setPlaceholderText('None')
        describe(self.options_edit, 'Extra ffmpeg options', OPTIONS_HELP)
        self.options_edit.setToolTip(OPTIONS_HELP)
        options_label = QLabel('Extra ffmpeg &options:')
        options_label.setBuddy(self.options_edit)
        form.addWidget(options_label, 1, 0)
        form.addWidget(self.options_edit, 1, 1)
        recordings_layout.addLayout(form)
        self.format_help = QLabel('')
        self.format_help.setWordWrap(True)
        recordings_layout.addWidget(self.format_help)
        self._show_format_help()
        options_help = QLabel(OPTIONS_HELP)
        options_help.setWordWrap(True)
        recordings_layout.addWidget(options_help)

        space_row = QHBoxLayout()
        space_label = QLabel('&Warn when free space is below:')
        self.space_spin = QSpinBox()
        self.space_spin.setRange(0, 10000)
        self.space_spin.setSuffix(' GB')
        self.space_spin.setSpecialValueText('Never')
        self.space_spin.setValue(host.low_space_gb())
        describe(self.space_spin, 'Warn when free space is below', SPACE_HELP)
        self.space_spin.setToolTip(SPACE_HELP)
        space_label.setBuddy(self.space_spin)
        space_row.addWidget(space_label)
        space_row.addWidget(self.space_spin)
        space_row.addStretch(1)
        recordings_layout.addLayout(space_row)

        self.early_spin = self.late_spin = None
        if getattr(host, 'builtin', None) is not None:
            early, late = host.recording_padding()
            padding_row = QHBoxLayout()
            early_label = QLabel('Built-in server: start &early by')
            self.early_spin = self._minutes_spin(early, 'Start recordings early by', early_label)
            late_label = QLabel('and end &late by')
            self.late_spin = self._minutes_spin(late, 'End recordings late by', late_label)
            for widget in (early_label, self.early_spin, late_label, self.late_spin):
                padding_row.addWidget(widget)
            padding_row.addStretch(1)
            recordings_layout.addLayout(padding_row)
            padding_help = QLabel(PADDING_HELP)
            padding_help.setWordWrap(True)
            recordings_layout.addWidget(padding_help)
        self.options_status = QLabel('')
        self.options_status.setWordWrap(True)
        recordings_layout.addWidget(self.options_status)
        recording_tab.addWidget(recordings)

        power = QGroupBox('Sleep')
        power_layout = QVBoxLayout(power)
        self.awake_check = QCheckBox('&Keep the computer awake for scheduled recordings')
        self.awake_check.setChecked(host.stays_awake_for_scheduled())
        describe(self.awake_check, description=AWAKE_HELP)
        power_layout.addWidget(self.awake_check)
        awake_help = QLabel(AWAKE_HELP)
        awake_help.setWordWrap(True)
        awake_help.setContentsMargins(24, 0, 0, 0)
        power_layout.addWidget(awake_help)
        recording_tab.addWidget(power)

        editing = QGroupBox('Converting for editing')
        editing_layout = QVBoxLayout(editing)
        self.convert_check = QCheckBox('Con&vert recordings for editing when they finish')
        self.convert_check.setChecked(host.converts_after_recording())
        describe(self.convert_check, description=CONVERT_HELP)
        editing_layout.addWidget(self.convert_check)
        convert_row = QHBoxLayout()
        convert_label = QLabel('Conversion op&tions:')
        self.convert_edit = QLineEdit(host.convert_options())
        convert_label.setBuddy(self.convert_edit)
        describe(self.convert_edit, 'Conversion options', 'ffmpeg options for the edit-friendly copy.')
        convert_row.addWidget(convert_label)
        convert_row.addWidget(self.convert_edit, 1)
        editing_layout.addLayout(convert_row)
        self.delete_check = QCheckBox('&Delete the original once a new recording is converted')
        self.delete_check.setChecked(host.deletes_converted_original())
        describe(
            self.delete_check,
            description='Only after a successful conversion. Recordings converted by hand are always kept.',
        )
        editing_layout.addWidget(self.delete_check)
        convert_help = QLabel(CONVERT_HELP)
        convert_help.setWordWrap(True)
        editing_layout.addWidget(convert_help)
        self.convert_status = QLabel('')
        self.convert_status.setWordWrap(True)
        editing_layout.addWidget(self.convert_status)
        recording_tab.addWidget(editing)
        recording_tab.addStretch(1)

        logos = QGroupBox('Channel logos')
        logos_layout = QVBoxLayout(logos)
        self.logos_check = QCheckBox('Show channel &logos')
        self.logos_check.setChecked(host.shows_channel_logos())
        describe(self.logos_check, description=LOGOS_HELP)
        logos_layout.addWidget(self.logos_check)
        logos_help = QLabel(PICON_HELP)
        logos_help.setWordWrap(True)
        logos_layout.addWidget(logos_help)
        picon_row = QHBoxLayout()
        self.picon_btn = QPushButton('&Download Picons')
        describe(self.picon_btn, 'Download Picons', PICON_HELP)
        self.picon_remove_btn = QPushButton('Remo&ve Picons')
        describe(self.picon_remove_btn, 'Remove Picons', 'Delete the downloaded picons.')
        picon_row.addWidget(self.picon_btn)
        picon_row.addWidget(self.picon_remove_btn)
        picon_row.addStretch(1)
        logos_layout.addLayout(picon_row)
        self.picon_progress = QProgressBar()
        self.picon_progress.setAccessibleName('Picon download')
        self.picon_progress.hide()
        logos_layout.addWidget(self.picon_progress)
        self.picon_status = QLabel('')
        self.picon_status.setWordWrap(True)
        logos_layout.addWidget(self.picon_status)
        general.addWidget(logos)

        group = QGroupBox('Imported channels')
        group_layout = QVBoxLayout(group)
        self.hide_check = QCheckBox('&Hide channels that do not work')
        self.hide_check.setChecked(host.hides_dead_channels())
        describe(self.hide_check, description=HIDE_HELP)
        group_layout.addWidget(self.hide_check)
        hide_help = QLabel(HIDE_HELP)
        hide_help.setWordWrap(True)
        hide_help.setContentsMargins(24, 0, 0, 0)
        group_layout.addWidget(hide_help)

        row = QHBoxLayout()
        self.check_btn = QPushButton('&Check Channels Now')
        describe(self.check_btn, 'Check Channels Now', CHECK_HELP)
        self.check_btn.setToolTip(CHECK_HELP)
        row.addWidget(self.check_btn)
        row.addStretch(1)
        group_layout.addLayout(row)
        self.status_label = QLabel('')
        self.status_label.setWordWrap(True)
        group_layout.addWidget(self.status_label)
        general.addWidget(group)
        general.addStretch(1)
        self.tabs.addTab(general_page, '&General')
        self.tabs.addTab(recordings_page, '&Recordings')
        layout.addWidget(self.tabs)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

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
        self.delete_check.setEnabled(self.convert_check.isChecked())
        self._show_convert_problem(self.convert_edit.text())
        self.hide_check.toggled.connect(self._toggled)
        self.check_btn.clicked.connect(self._check)
        self._sync()
        # Qt opens the window at its guessed minimum height, too low for the
        # wrapped help text, and squashes the rows. Size it for its width.
        width = max(self.minimumWidth(), self.sizeHint().width())
        height = layout.totalHeightForWidth(width)
        self.setMinimumHeight(height)
        self.resize(width, height)

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
        self.delete_check.setEnabled(on)

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
