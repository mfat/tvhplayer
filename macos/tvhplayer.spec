# -*- mode: python ; coding: utf-8 -*-
import sys
import os
from pathlib import Path

script_dir = os.getcwd()
project_dir = os.path.join(script_dir, 'tvhplayer')

# Define paths
icons_dir = os.path.join(script_dir, 'icons')

# Collect all icon files
icon_files = []
if os.path.exists(icons_dir):
    for file in os.listdir(icons_dir):
        if file.endswith(('.svg', '.png', '.ico')):
            icon_files.append((os.path.join(icons_dir, file), 'icons'))

block_cipher = None

a = Analysis(
    ['tvhplayer/tvhplayer.py'],
    pathex=[project_dir],
    binaries=[],
    datas=icon_files,
    hiddenimports=[
        'vlc',
        'PyQt5',
        'PyQt5.QtCore',
        'PyQt5.QtGui',
        'PyQt5.QtWidgets',
        'PyQt5.QtSvg',
        'requests',
        'certifi',
        'tvhplayer.resources_rc'
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# Improve VLC plugin handling for macOS
if sys.platform == 'darwin':
    vlc_locations = [
        '/Applications/VLC.app/Contents/MacOS/plugins',
        '/usr/local/lib/vlc/plugins',  # Homebrew installation
        str(Path.home() / 'Applications/VLC.app/Contents/MacOS/plugins')  # User installation
    ]
    
    for vlc_plugin_path in vlc_locations:
        if os.path.exists(vlc_plugin_path):
            for root, dirs, files in os.walk(vlc_plugin_path):
                for file in files:
                    if file.endswith(('.dylib', '.so')):  # Only include binary plugins
                        full_path = os.path.join(root, file)
                        rel_path = os.path.relpath(full_path, vlc_plugin_path)
                        a.binaries.append((
                            os.path.join('vlc', 'plugins', rel_path),
                            full_path,
                            'BINARY'
                        ))
            break  # Stop after finding first valid VLC installation

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,        # Include binaries in the exe
    a.zipfiles,        # Include zipfiles in the exe
    a.datas,          # Include datas in the exe
    name='TVHplayer',
    debug=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# Create the app bundle
app = BUNDLE(
    exe,
    name='TVHplayer.app',
    icon='tvhplayer.icns',  # Add the icon here
    bundle_identifier='com.tvhplayer.app',
    info_plist={
        'CFBundleName': 'TVHplayer',
        'CFBundleDisplayName': 'TVHplayer',
        'CFBundleGetInfoString': "TVHplayer",
        'CFBundleIdentifier': "com.tvhplayer.app",
        'CFBundleVersion': "3.2",
        'CFBundleShortVersionString': "3.2",
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '10.13.0',
        'NSRequiresAquaSystemAppearance': False,
        'VLCPluginPath': '@executable_path/../Resources/vlc/plugins',
        'NSAppleEventsUsageDescription': 'TVHplayer needs to control system features.',
        'NSCameraUsageDescription': 'TVHplayer does not use the camera.',
        'NSMicrophoneUsageDescription': 'TVHplayer does not use the microphone.',
    },
)