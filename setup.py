from setuptools import setup, find_packages

setup(
    name="tvhplayer",
    version="3.4",
    description="Desktop client for TVHeadend",
    author="mFat",
    author_email="mah.fat@gmail.com",
    url="https://github.com/mfat/tvhplayer",
    install_requires=[
        'PyQt6>=6.4.0',
        'python-vlc>=3.0.12122',
        # On Wayland, libmpv draws the picture so the window is not run through XWayland.
        'mpv>=1.0.4',
        'requests>=2.25.1',
        'python-dateutil>=2.8.2',
    ],
    python_requires='>=3.9',
    packages=find_packages(),
    package_data={
        'tvhplayer': ['*.py', 'icons/*'],
    },
    entry_points={
        'console_scripts': [
            'tvhplayer=tvhplayer.tvhplayer:main',
        ],
    },
    data_files=[
        ('share/applications', ['debian/tvhplayer.desktop']),
        ('share/icons/hicolor/256x256/apps', ['icons/tvhplayer.png']),
    ],
)