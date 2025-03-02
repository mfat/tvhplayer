#!/bin/bash
# Check for FFmpeg in Flatpak extension first
if [ -d "/app/lib/ffmpeg" ]; then
  export PATH="/app/lib/ffmpeg:$PATH"
  export LD_LIBRARY_PATH="/app/lib/ffmpeg:$LD_LIBRARY_PATH"
  echo "Using FFmpeg from Flatpak extension"
fi

# Print FFmpeg version for debugging
if command -v ffmpeg >/dev/null 2>&1; then
  echo "Using FFmpeg: $(which ffmpeg)"
  ffmpeg -version | head -n 1
else
  echo "Warning: FFmpeg not found. Local recording functionality will be unavailable."
fi

# Fix Qt platform plugin issue - use a single platform
export QT_QPA_PLATFORM=xcb

# Run the application
python3 /app/share/tvhplayer/tvhplayer.py "$@" 