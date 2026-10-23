# Proposal: mpv render engine for Wayland playback

- **Status:** Proposed
- **Date:** October 2026

## Problem

On Linux, TVHplayer plays video by embedding libvlc in a native Qt widget. `VlcPlayer.attach()` passes `video_frame.winId()` to `set_xwindow()`. That call accepts an X11 window id. `main()` therefore sets `QT_QPA_PLATFORM=xcb` before `QApplication` exists, so the id Qt returns is an X11 window.

On a Wayland desktop that choice applies to the whole process. The channel list, guide, and dialogs are X11 windows, and XWayland copies them into Wayland surfaces. At fractional scale the compositor scales that copy as a bitmap, so the interface is soft. The picture takes a longer path: libvlc draws into an X11 child, XWayland copies it, and the compositor shows the copy. Moving or resizing tracks an X11 window against a Wayland window, which is where a black gap or a one-frame lag comes from.

The Flatpak manifest already asks for a Wayland socket and treats X11 as a fallback (`--socket=wayland` and `--socket=fallback-x11` in `io.github.mfat.tvhplayer.yml`). The `xcb` default makes a Wayland session need XWayland anyway. With XWayland disabled, the app does not start. The desktop id `io.github.mfat.tvhplayer` is also what a native Wayland window uses for its icon and taskbar grouping.

The video widget is built for this embedding. `video_frame` is a native child (`WA_NativeWindow`, `WA_DontCreateNativeAncestors`). While a channel is starting or playing, `_show_playback_wait()` and `_protect_video_surface()` turn widget updates off so Qt will not paint over libvlc.

libvlc 3, which this app ships (Flatpak builds 3.0.21, macOS uses 3.0.24), exports `libvlc_media_player_set_xwindow()` and the memory-buffer callback `libvlc_video_set_callbacks()`. It does not export an OpenGL render callback or a Wayland surface setter. The installed 3.0.23 library matches that. There is no call on this libvlc that both draws inside a Qt widget and lets Qt stay on Wayland.

### Rejected approach

An unmerged libvlc fork adds `libvlc_media_player_set_wayland_surface()` and a window module that creates a `wl_subsurface` of the host surface. That function is not in upstream libvlc 3 or in current upstream master. The merge request targets the fork, and the author's account is deactivated.

The module also breaks the stop-then-play cycle this app already uses. The first `play()` creates the subsurface and shows a picture. Changing channel while a picture is up reuses the same enabled window, so that path survives. `Stop`, the end of a recording, or a stream error after a picture has been shown disables the window. Disable destroys the subsurface and stores a null pointer. The next `play()` reuses that window and calls `wl_subsurface_place_above()` on the null pointer. That is a `SIGSEGV`. The spinner appears, then the process exits. Qt never sees an exception, so there is no "Playback failed" dialog.

Shipping that fork would also replace the libvlc 3 packages on Windows and macOS, where the Wayland call does nothing, and `python-vlc` 3 cannot call `stop_async` or the new surface function. This proposal does not use that tree.

## Proposed solution

Add a Linux playback engine that uses stock libmpv and draws into a Qt OpenGL widget. mpv is started with `--vo=libmpv`, so it does not open a window. The widget owns the OpenGL context. When mpv has a frame, Qt repaints, and the engine calls `mpv_render_context_render()` into that widget's framebuffer.

This is the same arrangement Celluloid uses with GTK: a `GtkGLArea`, `mpv_render_context_create()` with `MPV_RENDER_API_TYPE_OPENGL`, and `MPV_RENDER_PARAM_WL_DISPLAY` set to the toolkit's `wl_display`. mpv 0.41, client API 2.5, exports those symbols in `libmpv.so.2`. The Wayland display parameter exists so hardware decoding can import frames into that GL context. The display must stay valid for the life of the render context.

`VlcPlayer` stays the engine for X11 sessions, Windows, and macOS. One launch uses one engine. The Qt platform is chosen before `QApplication`, so a running process cannot mix `xcb` embedding and a Wayland GL widget.

### When this engine is selected

`main()` chooses before creating `QApplication`:

| Session | Engine | `QT_QPA_PLATFORM` |
| :--- | :--- | :--- |
| Linux, `WAYLAND_DISPLAY` set, `libmpv.so.2` loads, and the user has not set `QT_QPA_PLATFORM` | mpv render engine | left unset, so Qt uses Wayland |
| Linux X11, or the user already set `QT_QPA_PLATFORM` | `VlcPlayer` | existing `setdefault("xcb")` |
| `libmpv` missing on a Wayland session | `VlcPlayer` | existing `setdefault("xcb")`, and a log line says why |
| Windows, macOS | `VlcPlayer` | unchanged |

`setdefault` remains for the libvlc path. It must not run when the mpv engine is selected. Forcing `xcb` and then asking mpv to render into a Wayland context would put the UI back on XWayland.

### Video widget

The mpv path does not use `video_frame` as a native X11 window.

- The picture surface is a `QOpenGLWidget` in `player_container`, with the same focus policy, accessible name, and context menu as `video_frame`.
- Qt keeps painting that widget. `_show_playback_wait()` and `_protect_video_surface()` must not call `setUpdatesEnabled(False)` on it. The idle splash and spinner stay sibling overlays on `player_container`.
- The framebuffer size passed to mpv is the widget size multiplied by `devicePixelRatio()`, the same role `gdk_surface_get_scale_factor()` plays in Celluloid.
- Mouse and keyboard stay with Qt. `VlcPlayer` already turns off libvlc mouse and key grabbing for that reason. mpv has no video window to grab them.

`Player.attach(window_id)` cannot describe this. A window id is what `set_xwindow()`, `set_hwnd()`, and `set_nsobject()` consume. The mpv engine needs the OpenGL widget, a repaint when a frame is ready, and the current framebuffer during that paint. `VlcPlayer.attach(winId)` stays for the libvlc path. The window branches on which engine it constructed. The shared `play`, `stop`, `is_playing`, volume, mute, and handler methods stay as they are.

### Render loop

1. Create one mpv handle and one render context for the life of the engine. Load the next URL with `loadfile` on that handle. Do not destroy the render context on stop or on a channel change.
2. Create the render context on the widget's GL thread, with the widget context current. Pass `MPV_RENDER_API_TYPE_OPENGL`. On Wayland, pass the process `wl_display` from Qt's native interface as `MPV_RENDER_PARAM_WL_DISPLAY`.
3. mpv's render-update callback schedules work on the Qt thread. If the update includes a new frame, the widget repaints.
4. The widget's paint reads the bound framebuffer and calls `mpv_render_context_render()` with that framebuffer, the pixel size, and the Y flip mpv's OpenGL renderer requires.
5. Hardware decoding is requested (`hwdec` auto, or the closest mpv equivalent of `--avcodec-hw=any`). The `wl_display` parameter is what makes that import possible. If the driver cannot import, mpv falls back inside the same context. Playback still has a picture.

Stop sets mpv's idle state and tells the window that playback stopped. The render context and the GL widget remain. The next `play()` loads another URL into the same context. That is the cycle the Wayland subsurface module crashes on, and this engine does not allocate a subsurface.

`MediaPlayerPlaying`, `MediaPlayerStopped`, `MediaPlayerEndReached`, and `MediaPlayerEncounteredError` map to the existing `on_playing`, `on_stopped`, and `on_error` handlers. End of a recording and an open failure still reach the handlers the splash already uses. Events arrive on mpv's thread. `schedule` continues to hop them onto the Qt thread.

### Proxy and audio

`hide_http_proxy_from_vlc()` stays inside `VlcPlayer`. It exists because libvlc 3 sends every `http://` URL through `http_proxy` and ignores `no_proxy`. The mpv engine does not call it. Its first test against a loopback or LAN Tvheadend must show the request going directly when `no_proxy` covers that host. If mpv does not honor `no_proxy`, the engine gets its own narrow fix. It does not reuse the libvlc environment hack.

Audio output is mpv's default. The Flatpak manifest already has `--socket=pulseaudio`.

### Packaging

- Runtime dependency on Linux: `libmpv.so.2` (mpv 0.41 or another build with client API 2 and the render API). The Python binding is `python-mpv`, alongside `python-vlc`.
- Flatpak: add mpv to `io.github.mfat.tvhplayer.yml`. The existing libvlc 3.0.21 module stays for the `xcb` fallback.
- Windows and macOS packages do not gain libmpv in this pass. They keep `VlcPlayer`.
- Do not build or ship the unmerged libvlc fork.

### Out of scope

- Replacing `VlcPlayer` on X11, Windows, or macOS.
- Qt Multimedia. It can also draw inside Qt, and it is a different decoder and buffering stack. This proposal is the mpv render path.
- A GTK `GtkGraphicsOffload` equivalent. Celluloid can promote its GL area to a Wayland subsurface, and that setting defaults to off. The first version renders into the widget framebuffer.
- Changing channel lists, DVR, or the built-in server.

## Test plan

On a Wayland session with `libmpv.so.2` present and `QT_QPA_PLATFORM` unset:

- The process platform is Wayland. `xcb` was not forced.
- The first channel shows a picture inside the player pane. The splash hides when playback starts.
- Changing channel while a picture is up replaces the picture and leaves the window up.
- Stop shows the splash and "Playback stopped". The next channel, or a recording, plays again. The process does not exit.
- A recording that reaches the end shows the splash. Playing something afterwards works.
- At 125% or 150% scale the controls and the picture stay sharp.
- Mute, volume, fullscreen, and the video context menu still work. Qt receives the keys.

On an X11 session, and on Wayland with `QT_QPA_PLATFORM=xcb` already set, or with `libmpv` absent:

- `VlcPlayer` is used and the current embedding behavior is unchanged.

Windows and macOS builds are unchanged.
