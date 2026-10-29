"""The Settings window: playback at startup, where recordings go, and imported channels that do not work.

Layout: a sidebar of pages (Appearance, Playback, Channels, Recordings, Conversion, Sleep, Updates). Every setting is a
row with its name and description on the left and the control on the right. The settings logic and
the widget attribute names are unchanged from the tabbed version.
"""

from __future__ import annotations


from PyQt6.QtCore import QEvent, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap
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
    from .core.config import SCHEME_CHOICES, SCHEME_DARK, SCHEME_LIGHT, SCHEME_SYSTEM, THEME_ORGANIC, THEME_TVHPLAYER
    from .ui_theme import accent_choices, accent_swatch, style_names, window_color_choices, window_swatch
    from .settings_widgets import SettingRow, SettingsGroup, SettingsNav, SettingsPage, StatusStrip, ToggleSwitch
except ImportError:
    from a11y import announce_label, describe
    from core.recorder import RECORDING_FORMATS, parse_ffmpeg_options
    from core.config import SCHEME_CHOICES, SCHEME_DARK, SCHEME_LIGHT, SCHEME_SYSTEM, THEME_ORGANIC, THEME_TVHPLAYER
    from ui_theme import accent_choices, accent_swatch, style_names, window_color_choices, window_swatch
    from settings_widgets import SettingRow, SettingsGroup, SettingsNav, SettingsPage, StatusStrip, ToggleSwitch

THEME_SHORT = ("TVHplayer is the app's own look, and Organic its rounder, warmer one, as in Jottr. "
               "The others are the styles Qt offers on this computer.")
SCHEME_SHORT = 'Follow system theme, or set Light/Dark theme manually'
ACCENT_SHORT = 'Color of selections, focus and the main buttons'
WINDOW_COLOR_SHORT = 'Background of windows and panels in the TVHplayer and Organic styles'
SCHEME_NAMES = {SCHEME_SYSTEM: 'Follow System', SCHEME_LIGHT: 'Light', SCHEME_DARK: 'Dark'}
HIDE_HELP = (
    'After an import or refresh, the server tests each channel in the background. '
    'Channels that fail are hidden and come back once a later test finds them working.'
)
PLAY_HELP = 'Once the channel list has loaded, the channel you watched last starts playing.'
LIVE_RESIZE_HELP = (
    'Show new video size in real time when resizing the sidebar. '
    'Turn this off if resizing is slow.'
)
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
TITLE_BAR_HELP = 'Takes effect the next time TVHplayer starts.'
UPDATES_HELP = 'Once a day, TVHplayer asks GitHub whether a newer version has been released and tells you if so.'
UPDATES_NOW_HELP = 'Ask GitHub now. A version you skipped is shown again.'


def _swatch_icon(fill, edge, size=14):
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(edge)
    painter.setBrush(QColor(fill))
    painter.drawEllipse(QRectF(0.5, 0.5, size - 1, size - 1))
    painter.end()
    return QIcon(pixmap)


class SettingsDialog(QDialog):
    """``host`` is the main window: it keeps the setting and runs the checks."""

    PAGES = (
        ('Appearance', 'Theme, light or dark'),
        ('Playback', 'Startup, panes'),
        ('Channels', 'Logos, imported playlists'),
        ('Recordings', 'Folder, format, padding'),
        ('Conversion', 'Edit-friendly copies'),
        ('Sleep', 'Scheduled recordings'),
        ('Updates', 'New versions'),
    )

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self._host = host
        self._jobs = []
        self.setWindowTitle('Settings')
        # Not modal: on Wayland GNOME keeps the pointer off the window behind a
        # modal dialog, where it then keeps the resize arrow of the dialog's edge.
        self.setModal(False)
        self.setAccessibleName('Settings')
        self.setMinimumSize(720, 520)
        self.resize(860, 640)
        has_builtin = getattr(host, 'builtin', None) is not None

        pages = [
            self._appearance_page(host),
            self._playback_page(host),
            self._channels_page(host),
            self._recordings_page(host, has_builtin),
            self._conversion_page(host),
            self._sleep_page(host),
            self._updates_page(host),
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
        self.live_resize_check.toggled.connect(host.set_uses_live_resize)
        self.folder_btn.clicked.connect(self._choose_folder)
        self.format_combo.currentIndexChanged.connect(self._format_chosen)
        self.options_edit.editingFinished.connect(self._options_edited)
        self.convert_check.toggled.connect(self._convert_toggled)
        self.convert_edit.editingFinished.connect(self._convert_edited)
        self.delete_check.toggled.connect(host.set_deletes_converted_original)
        self.awake_check.toggled.connect(host.set_stays_awake_for_scheduled)
        self.updates_check.toggled.connect(host.set_checks_for_updates)
        self.updates_btn.clicked.connect(host.check_for_updates)
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
        panes = page.add(SettingsGroup('Panes'))
        self.live_resize_check = ToggleSwitch('Live resize')
        self.live_resize_check.setChecked(host.uses_live_resize())
        describe(self.live_resize_check, description=LIVE_RESIZE_HELP)
        panes.add_row(SettingRow('&Live resize', LIVE_RESIZE_HELP, self.live_resize_check))
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

    def _updates_page(self, host):
        page = SettingsPage('Updates')
        group = page.add(SettingsGroup())
        self.updates_check = ToggleSwitch('Check for updates automatically')
        self.updates_check.setChecked(host.checks_for_updates())
        describe(self.updates_check, description=UPDATES_HELP)
        group.add_row(SettingRow('&Check for updates automatically', UPDATES_HELP, self.updates_check))
        self.updates_btn = QPushButton('Check &Now')
        describe(self.updates_btn, 'Check for Updates Now', UPDATES_NOW_HELP)
        self.updates_btn.setToolTip(UPDATES_NOW_HELP)
        group.add_row(SettingRow('Check for updates now', UPDATES_NOW_HELP, self.updates_btn))
        page.finish()
        return page

    def _appearance_page(self, host):
        page = SettingsPage('Appearance')
        group = page.add(SettingsGroup('Theme'))
        self.theme_combo = QComboBox()
        self.theme_combo.setMinimumWidth(170)
        self.theme_combo.addItem('TVHplayer', THEME_TVHPLAYER)
        self.theme_combo.addItem('Organic', THEME_ORGANIC)
        for name in style_names():
            self.theme_combo.addItem(name, name)
        chosen = host.theme_choice()
        index = self.theme_combo.findData(chosen)
        if index < 0:
            index = next((i for i in range(self.theme_combo.count())
                          if str(self.theme_combo.itemData(i)).casefold() == chosen.casefold()), 0)
        self.theme_combo.setCurrentIndex(index)
        describe(self.theme_combo, 'Application style', THEME_SHORT)
        group.add_row(SettingRow('&Application style', THEME_SHORT, self.theme_combo))
        self.scheme_combo = QComboBox()
        self.scheme_combo.setMinimumWidth(170)
        for mode in SCHEME_CHOICES:
            self.scheme_combo.addItem(SCHEME_NAMES[mode], mode)
        self.scheme_combo.setCurrentIndex(max(0, self.scheme_combo.findData(host.color_scheme_choice())))
        describe(self.scheme_combo, 'Theme', SCHEME_SHORT)
        group.add_row(SettingRow('&Theme', SCHEME_SHORT, self.scheme_combo))
        self.accent_combo = self._swatch_combo(accent_choices(), host.accent_choice())
        describe(self.accent_combo, 'Accent color', ACCENT_SHORT)
        group.add_row(SettingRow('Acc&ent color', ACCENT_SHORT, self.accent_combo))
        self.window_color_combo = self._swatch_combo(window_color_choices(), host.window_color_choice())
        describe(self.window_color_combo, 'Window color', WINDOW_COLOR_SHORT)
        self._window_color_group = group
        self._window_color_row = group.add_row(SettingRow(
            '&Window color', WINDOW_COLOR_SHORT, self.window_color_combo))
        self._show_window_color_row()
        self._paint_swatches()
        # GNOME and KDE; on X11 only while a compositor can show the shadow. Shown
        # as the next start will be, since the engine chosen decides Wayland or X11.
        self.title_bar_check = ToggleSwitch("Use TVHplayer's own title bar")
        self.title_bar_check.setChecked(host.draws_title_bar())
        describe(self.title_bar_check, description=TITLE_BAR_HELP)
        self._title_bar_group = group
        self._title_bar_row = group.add_row(SettingRow(
            "Use TVHplayer's own title &bar", TITLE_BAR_HELP, self.title_bar_check))
        self.title_bar_check.toggled.connect(host.set_draws_title_bar)
        self._show_title_bar_row()
        self.theme_combo.currentIndexChanged.connect(self._theme_chosen)
        self.scheme_combo.currentIndexChanged.connect(self._scheme_chosen)
        self.accent_combo.currentIndexChanged.connect(self._accent_chosen)
        self.window_color_combo.currentIndexChanged.connect(self._window_color_chosen)
        page.finish()
        return page

    # Behaviour (unchanged from the tabbed dialog) --------------------------

    def _theme_chosen(self, _index):
        # Once the list has closed: a theme change restyles every widget, the list's too.
        QTimer.singleShot(0, self._use_chosen_theme)

    def _use_chosen_theme(self):
        self._host.set_theme_choice(self.theme_combo.currentData())
        self._show_window_color_row()

    def _accent_chosen(self, _index):
        # Once the list has closed, as for the theme.
        QTimer.singleShot(0, lambda: self._host.set_accent_choice(self.accent_combo.currentData()))

    def _window_color_chosen(self, _index):
        QTimer.singleShot(0, lambda: self._host.set_window_color_choice(self.window_color_combo.currentData()))

    def _show_window_color_row(self):
        self._window_color_group.set_row_visible(
            self._window_color_row, self.theme_combo.currentData() in (THEME_TVHPLAYER, THEME_ORGANIC))

    @staticmethod
    def _swatch_combo(choices, chosen):
        combo = QComboBox()
        combo.setMinimumWidth(170)
        for key, label in choices:
            combo.addItem(label, key)
        combo.setCurrentIndex(max(0, combo.findData(chosen)))
        return combo

    def _paint_swatches(self):
        """Swatches show each color as it looks in the scheme in use."""
        edge = self.palette().color(QPalette.ColorRole.WindowText)
        edge.setAlpha(90)
        for combo, swatch in ((self.accent_combo, accent_swatch), (self.window_color_combo, window_swatch)):
            for i in range(combo.count()):
                combo.setItemIcon(i, _swatch_icon(swatch(combo.itemData(i)), edge))

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange and hasattr(self, 'window_color_combo'):
            self._paint_swatches()

    def _scheme_chosen(self, _index):
        # Once the list has closed, as for the theme: the new colors repaint every widget.
        QTimer.singleShot(0, lambda: self._host.set_color_scheme_choice(self.scheme_combo.currentData()))

    def _show_title_bar_row(self):
        self._title_bar_group.set_row_visible(self._title_bar_row, self._host.can_draw_title_bar())

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
        orphans = sum(1 for source in self._host.playlist_sources() if self._host.server_for_playlist(source) is None)
        not_checked = ''
        if orphans:
            not_checked = (
                'The server of 1 playlist was removed, so it cannot be checked.' if orphans == 1
                else f'The servers of {orphans} playlists were removed, so they cannot be checked.'
            )
        if not self._jobs:
            announce_label(self.status_label, not_checked or 'There are no imported playlists to check.')
            return
        for job in self._jobs:
            job.finished.connect(lambda *_args: self._sync())
            job.failed.connect(lambda *_args: self._sync())
        count = len(self._jobs)
        playlists = '1 playlist' if count == 1 else f'{count} playlists'
        announce_label(
            self.status_label,
            f'Checking {playlists} in the background. Channels that do not work are hidden as they are found; '
            f'the status bar says when it is done. {not_checked}'.rstrip(),
        )
        self._sync()

    def _sync(self):
        running = bool(self._host.playlist_checks())
        self.check_btn.setEnabled(not running)
        if running:
            self.check_btn.setToolTip('Channels are being checked.')
        else:
            self.check_btn.setToolTip(CHECK_HELP)
