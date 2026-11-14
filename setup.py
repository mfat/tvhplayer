from setuptools import Extension, setup, find_packages

# HTSMSG decoding in C. Packages build it in place before copying tvhplayer/:
#   python3 setup.py build_ext --inplace
# Without it the app decodes in Python, which is slow for large channel lists.
HTSMSG = Extension('tvhplayer.core._htsmsg', ['tvhplayer/core/_htsmsg.c'], optional=True)

setup(
    name="tvhplayer",
    version="4.6.5",
    description="Desktop client for TVHeadend",
    author="mFat",
    author_email="mah.fat@gmail.com",
    url="https://github.com/mfat/tvhplayer",
    install_requires=[
        'PyQt6>=6.4.0',
        'mpv>=1.0.4',
        'PyChromecast>=14.1.0; python_version >= "3.11"',
        'PyChromecast>=13.1.0,<14; python_version < "3.11"',
        'requests>=2.25.1',
        'python-dateutil>=2.8.2',
    ],
    python_requires='>=3.9',
    packages=find_packages(),
    ext_modules=[HTSMSG],
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
