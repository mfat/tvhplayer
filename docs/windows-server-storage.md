# Windows built-in server settings

The Windows built-in server keeps its working settings in a persistent WSLc
Linux volume. This avoids reading thousands of small TVHeadend files across a
Windows bind mount on every start. Recordings remain in the selected Windows
recording folder.

On the first start after upgrading, TVHplayer archives the existing server
settings, imports them into a private named volume, and marks the migration
complete only after the import succeeds. Interrupted imports can be retried.
The original Windows settings are preserved, but are no longer the live settings
after migration.

Each start checks the Windows settings folder's current permissions, but only
reapplies them if the expected private permissions are absent. The playlist
FFmpeg migration runs once per server image and settings generation. Restoring
settings creates a new generation so a previous migration marker cannot skip
checking the restored playlists.

Storage records and backups are under
`%APPDATA%\TVHplayer\tvheadend\.tvhplayer-storage`:

- `state.json` identifies the owned Linux volume. Keep this file.
- `seed.tar` preserves the settings used for the initial migration.
- `latest.tar.gz` and `previous.tar.gz` are older shutdown copies, when present.
  A server start, including one that changes the server image, does not create
  a new copy. Older `before-upgrade-*.tar.gz` files are leftovers from that
  removed step.

These files contain server credentials and inherit the private settings folder's
Windows permissions. Do not share them publicly.

If the volume is missing, TVHplayer restores the latest available shutdown backup
into a new owned volume. It refuses to silently reset to the stale Windows
settings when no current backup exists. Settings written before an app crash
remain in the Linux volume; a crash does not remove the volume. Avoid deleting
or pruning the volume. Restoring an older executable alone does not move current
Linux settings back into the original Windows settings tree.
