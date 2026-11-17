"""Keep the existing supervised server alive while all player windows are hidden."""

from __future__ import annotations

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

try:
    from .core.updates import installed_by_flatpak
except ImportError:
    from core.updates import installed_by_flatpak


class BackgroundMode(QObject):
    changed = pyqtSignal()

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.hidden = False
        self.quitting = False
        self.session_ending = False
        self.pending = False
        self._hide_when_granted = False
        self.flatpak = installed_by_flatpak()
        self.granted = not self.flatpak
        self.portal = None
        self.tray = None
        self._hidden_windows = []
        self.deferred_setup = False
        self.deferred_update = None

    @property
    def enabled(self):
        return bool(self.window.config.get('keep_builtin_running'))

    def set_enabled(self, enabled):
        if not enabled:
            self.granted = not self.flatpak
            self._hide_when_granted = False
            if self.portal is not None:
                self.portal.cancel()
            self.pending = False
            self.window.config['keep_builtin_running'] = False
            self.window.save_config()
            self.changed.emit()
            if self.tray is not None:
                self.tray.hide()
            return
        if self.window.builtin is None:
            return
        if self.granted:
            self._permission(True, '')
            return
        if self.pending:
            return
        try:
            from .background_portal import BackgroundPortal
        except ImportError:
            try:
                from background_portal import BackgroundPortal
            except ImportError:
                self._permission(False, 'This installation does not provide desktop background support.')
                return
        if self.portal is None:
            self.portal = BackgroundPortal(self)
            self.portal.finished.connect(self._permission)
        self.pending = True
        self.changed.emit()
        self.portal.request()

    def _permission(self, granted, reason):
        self.pending = False
        self.granted = granted
        self.window.config['keep_builtin_running'] = granted
        self.window.save_config()
        self.changed.emit()
        hide, self._hide_when_granted = self._hide_when_granted, False
        if granted:
            self._ensure_tray()
            if hide and not self.quitting:
                self.window.close()
        else:
            QMessageBox.warning(self.window, 'Background Mode Unavailable', reason)

    def _ensure_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        if self.tray is None:
            self.tray = QSystemTrayIcon(self.window.windowIcon(), self)
            self.tray.setToolTip('TVHplayer — built-in server')
            menu = QMenu(self.window)
            menu.addAction('Open TVHplayer', self.show_window)
            menu.addSeparator()
            menu.addAction('Quit TVHplayer', self.quit)
            self.tray.setContextMenu(menu)
            self.tray.activated.connect(self._activated)
        self.tray.show()

    def _activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_window()

    def close_to_background(self):
        if self.pending and not self.quitting:
            self._hide_when_granted = True
            return True
        if self.quitting or not self.enabled or self.window.builtin is None:
            return False
        # Never hide an idle app with no owned server to keep alive.
        if self.window.builtin.status not in ('starting', 'installing', 'running', 'stopping'):
            return False
        if not self.granted:
            self._hide_when_granted = True
            self.set_enabled(True)
            # Permission UI finishes while the window is still open.
            return True
        if self.hidden:
            return True
        window = self.window
        if window._settings_dialog is not None:
            window._settings_dialog.close()
        window.save_config()
        window._play_generation += 1  # Discard a stream URL already in flight.
        window._play_on_start = False
        window.stop_playback()
        self._hidden_windows = [w for w in QApplication.topLevelWidgets()
                                if w is not window and w.isVisible() and window.isAncestorOf(w)]
        for child in self._hidden_windows:
            child.hide()
        # hide(), not showMinimized(): leave no mapped player window for the
        # desktop portal to classify as a running foreground application.
        window.hide()
        self.hidden = True
        window._metadata_timer.stop()
        window._now_next_timer.stop()
        self._ensure_tray()
        if self.portal is not None:
            self.portal.set_status('TV server running; scheduled recordings remain active')
        return True

    def show_window(self):
        if self.quitting:
            return
        self.hidden = False
        self._hide_when_granted = False
        window = self.window
        if window.windowState() & Qt.WindowState.WindowMinimized:
            window.setWindowState(window.windowState() & ~Qt.WindowState.WindowMinimized)
        window.show()
        window.raise_()
        window.activateWindow()
        for child in self._hidden_windows:
            try:
                child.show()
            except RuntimeError:  # A delete-on-close dialog may have finished meanwhile.
                pass
        self._hidden_windows.clear()
        window._metadata_timer.start()
        window._now_next_timer.start()
        if self.portal is not None:
            self.portal.set_status('')
        if self.deferred_setup:
            self.deferred_setup = False
            QTimer.singleShot(0, window._offer_channel_setup)
        if self.deferred_update is not None:
            release, self.deferred_update = self.deferred_update, None
            QTimer.singleShot(0, lambda: window._show_update_available(release))

    def quit(self):
        if self.window._closing:
            return
        self.quitting = True
        self._hide_when_granted = False
        # Recording confirmations need a visible parent, including on desktops
        # without a tray. Preserve the existing asynchronous recording lookup.
        self.hidden = False
        self.window.show()
        self.window.raise_()
        self.window.close()
        if not self.window._closing and getattr(self.window, '_quit_lookup_call', None) is None:
            self.quitting = False

    def end_session(self, manager):
        self.session_ending = True
        self.quitting = True
        self.window.close()

    def shutdown(self):
        if self.portal is not None:
            self.portal.cancel()
        if self.tray is not None:
            self.tray.hide()
