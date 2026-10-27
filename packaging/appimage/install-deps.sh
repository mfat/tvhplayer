#!/bin/sh
# Install what build-appimage.sh needs on Ubuntu 24.04. Run as root.
set -eu

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
    ca-certificates curl file patchelf \
    python3.12 python3-pip \
    build-essential pkgconf gettext bzip2 cmake \
    libssl-dev zlib1g-dev libpcre2-dev libdbus-1-dev \
    libmpv2 ffmpeg \
    libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 \
    libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 libxcb-xkb1 libxkbcommon-x11-0 \
    libxkbcommon0 libegl1 libgl1 libopengl0 libdbus-1-3 libwayland-cursor0 libwayland-egl1
