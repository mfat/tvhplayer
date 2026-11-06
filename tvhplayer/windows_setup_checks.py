"""A compact checklist shown only after built-in server startup fails."""
import re
from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QStyle, QPlainTextEdit

try:
    from .core.logs import sanitize
except ImportError:
    from core.logs import sanitize


TITLES = {
    'wsl': ('WSL is installed', 'WSL is not installed', 'WSL installation — not checked'),
    'version': ('WSL version is supported', 'WSL needs an update', 'WSL version — not checked'),
    'virtualization': ('Virtualization is on', 'Virtualization is turned off or unavailable',
                       'Virtualization — not checked'),
    'platform': ('Windows virtualization support is on', 'Windows virtualization support is off',
                 'Windows support — not checked'),
    'server': ('Built-in server is ready', 'Built-in server could not start',
               'Built-in server — not checked'),
    'image': ('Server image is ready', 'Server files need attention', 'Server image — not checked'),
}
HELP = {
    'bios': 'Turn on Intel Virtualization Technology (VT-x) or AMD SVM in BIOS/UEFI, then restart Windows.',
    'repair': 'Turn on this Windows feature, then restart your computer.',
    'install': 'Install WSL, the Windows component the built-in server needs. Administrator permission is required.',
    'update': 'Update WSL to a version that supports the built-in server.',
    'reboot': 'Save your work and restart Windows. Then reopen TVHplayer.',
    'diagnose': 'Open troubleshooting help to check what is preventing the server from starting.',
    'image': 'Download and extract TVHplayer again to restore the server files. Your settings can be kept.',
}
BUTTONS = {'bios': 'How to turn it on', 'repair': 'Enable Virtual Machine Platform…',
           'install': 'Install WSL…', 'update': 'Update WSL…', 'diagnose': 'Troubleshooting help',
           'image': 'Download TVHplayer'}


def problem_summary(message):
    text = message.lower()
    if any(word in text for word in ('checksum', 'offline backend', 'offline archive', 'bundle')):
        return 'The server files are missing or could not be verified.'
    if any(word in text for word in ('permission', 'access denied', 'secure the backend', 'acl')):
        return 'TVHplayer could not access its server settings folder.'
    if re.search(r'\bports?\b|address already in use', text):
        return 'The server could not open the connections it needs.'
    if any(word in text for word in ('timed out', 'timeout', 'did not answer')):
        return 'The server took too long to respond.'
    if 'configure backend' in text or 'configure the server' in text:
        return 'Some required server settings could not be applied.'
    return 'The built-in server could not start. Technical details are available below.'


class WindowsSetupChecks(QWidget):
    action_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []
        self.labels = {}
        self.help_labels = {}
        self.buttons = {}
        self.diagnostics = ''
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(12)

    def set_checks(self, rows, fix_button=None, fix_action=None):
        self.details_panel = None
        if fix_button is not None:
            fix_button.setParent(self)
            fix_button.hide()
        while self.box.count():
            item = self.box.takeAt(0)
            item.widget().deleteLater()
        self.rows = rows
        self.labels, self.help_labels, self.buttons = {}, {}, {}
        for row in rows:
            key, status = row.get('key'), row.get('status', 'pending')
            if key not in TITLES:
                continue
            section = QWidget(self)
            layout = QVBoxLayout(section)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(5)
            line = QHBoxLayout()
            icon = QLabel()
            icon.setFixedWidth(22)
            if status in ('passed', 'failed'):
                standard = (QStyle.StandardPixmap.SP_DialogApplyButton if status == 'passed'
                            else QStyle.StandardPixmap.SP_MessageBoxWarning)
                icon.setPixmap(self.style().standardIcon(standard).pixmap(18, 18))
            else:
                icon.setText('○')
            title = TITLES[key][{'passed': 0, 'failed': 1}.get(status, 2)]
            action = row.get('action', 'diagnose')
            if status == 'failed' and action == 'reboot':
                title = 'Windows needs a restart'
            label = QLabel(title)
            label.setWordWrap(True)
            label.setAccessibleName(f'{status.capitalize()}: {title}')
            self.labels[key] = label
            line.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
            line.addWidget(label, 1)
            layout.addLayout(line)
            if status == 'failed':
                help_label = QLabel(HELP.get(action, HELP['diagnose']))
                help_label.setWordWrap(True)
                help_label.setContentsMargins(28, 0, 0, 0)
                layout.addWidget(help_label)
                self.help_labels[key] = help_label
                if action in BUTTONS:
                    button = (fix_button if fix_button is not None and action == fix_action
                              and action in ('install', 'update', 'repair') else QPushButton(BUTTONS[action]))
                    if button is not fix_button:
                        button.clicked.connect(lambda _checked=False, action=action: self._action(action))
                    button.setText(BUTTONS[action])
                    layout.addWidget(button, 0, Qt.AlignmentFlag.AlignLeft)
                    button.show()
                    self.buttons[action] = button
            self.box.addWidget(section)
        if self.diagnostics:
            self.set_diagnostics(self.diagnostics)

    def set_diagnostics(self, message):
        self.diagnostics = sanitize(message)
        previous = getattr(self, 'details_panel', None)
        if previous is not None:
            self.box.removeWidget(previous)
            previous.deleteLater()
        self.details_panel = QWidget(self)
        layout = QVBoxLayout(self.details_panel)
        layout.setContentsMargins(0, 6, 0, 0)
        self.details_toggle = QPushButton('Technical details')
        self.details_toggle.setCheckable(True)
        self.details_text = QPlainTextEdit(self.diagnostics)
        self.details_text.setReadOnly(True)
        self.details_text.setMaximumHeight(150)
        self.details_text.hide()
        self.copy_details = QPushButton('Copy details')
        self.copy_details.hide()
        self.details_toggle.toggled.connect(self.details_text.setVisible)
        self.details_toggle.toggled.connect(self.copy_details.setVisible)
        self.copy_details.clicked.connect(lambda: QApplication.clipboard().setText(self.diagnostics))
        layout.addWidget(self.details_toggle)
        layout.addWidget(self.details_text)
        layout.addWidget(self.copy_details, 0, Qt.AlignmentFlag.AlignLeft)
        self.box.addWidget(self.details_panel)
        self.details_panel.setVisible(bool(self.diagnostics))

    def _action(self, action):
        if action in ('bios', 'diagnose', 'image'):
            url = ('https://support.microsoft.com/windows/c5578302-6e43-4b4b-a449-8ced115f58e1'
                   if action == 'bios' else 'https://github.com/mfat/tvhplayer/releases/latest'
                   if action == 'image' else 'https://learn.microsoft.com/en-us/windows/wsl/troubleshooting')
            QDesktopServices.openUrl(QUrl(url))
        else:
            self.action_requested.emit(action)
