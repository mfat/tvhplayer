"""A compact checklist shown only after built-in server startup fails."""
from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QStyle


TITLES = {
    'wsl': ('WSL is installed', 'WSL is not installed', 'WSL installation — not checked'),
    'version': ('WSL version is supported', 'WSL needs an update', 'WSL version — not checked'),
    'virtualization': ('Virtualization is on', 'Virtualization is turned off or unavailable',
                       'Virtualization — not checked'),
    'platform': ('Windows virtualization support is on', 'Windows virtualization support is off',
                 'Windows support — not checked'),
    'server': ('Built-in server is ready', 'Built-in server could not start',
               'Built-in server — not checked'),
}
HELP = {
    'bios': 'Turn on Intel Virtualization Technology (VT-x) or AMD SVM in BIOS/UEFI, then restart Windows.',
    'repair': 'Turn on this Windows feature, then restart your computer.',
    'install': 'Install WSL, the Windows component the built-in server needs. Administrator permission is required.',
    'update': 'Update WSL to a version that supports the built-in server.',
    'reboot': 'Save your work and restart Windows. Then reopen TVHplayer.',
    'diagnose': 'Open troubleshooting help to check what is preventing the server from starting.',
}
BUTTONS = {'bios': 'How to turn it on', 'repair': 'Enable Virtual Machine Platform…',
           'install': 'Install WSL…', 'update': 'Update WSL…', 'diagnose': 'Troubleshooting help'}


class WindowsSetupChecks(QWidget):
    action_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []
        self.labels = {}
        self.help_labels = {}
        self.buttons = {}
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(12)

    def set_checks(self, rows, fix_button=None, fix_action=None):
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

    def _action(self, action):
        if action in ('bios', 'diagnose'):
            url = ('https://support.microsoft.com/windows/c5578302-6e43-4b4b-a449-8ced115f58e1'
                   if action == 'bios' else 'https://learn.microsoft.com/en-us/windows/wsl/troubleshooting')
            QDesktopServices.openUrl(QUrl(url))
        else:
            self.action_requested.emit(action)
