#!/bin/bash
# Check for FFmpeg in various locations
if [ -x "/usr/bin/ffmpeg" ]; then
  export PATH="/usr/bin:$PATH"
elif [ -d "/usr/lib/ffmpeg" ]; then
  export PATH="/usr/lib/ffmpeg:$PATH"
elif [ -d "/app/lib/ffmpeg" ]; then
  export PATH="/app/lib/ffmpeg:$PATH"
fi

# Print FFmpeg version for debugging
if command -v ffmpeg >/dev/null 2>&1; then
  echo "Using FFmpeg: $(which ffmpeg)"
  ffmpeg -version | head -n 1
else
  echo "Warning: FFmpeg not found. Local recording functionality will be unavailable."
fi

# Run the application
python3 /app/share/tvhplayer/tvhplayer.py "$@" 