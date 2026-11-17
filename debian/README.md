# TVHplayer

A desktop client for TVheadend for live TV playback and recording.

## Features
* Live TV playback
* EPG (Electronic Program Guide)
* Recording management
* Multiple TVheadend server support

## License
GPL-3.0

## Python compatibility

The same deb is used on Ubuntu 24.04 and Debian 13, with one package per
architecture. Its HTSP C decoder is built with Python's stable ABI (`abi3`)
for Python 3.11 and newer, rather than for the build machine's Python minor
version. **Both building and running the deb require Python 3.11 or newer.**
The system libraries must also satisfy the generated package dependencies;
the Python minimum alone does not imply support for older distributions.
Keep the minimum Python dependency in `debian/control` in sync
with `Py_LIMITED_API` in `packaging/build-native.py`.
The stable extension is installed after `dh_python3`'s scan because the older
version on Ubuntu 24.04 otherwise assigns it a Python 3.12-only dependency.

CI installs and smoke-tests the Ubuntu-built package on both distributions,
including loading and using the packaged C decoder.
