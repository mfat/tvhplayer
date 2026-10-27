# Proposal: mpv render engine for Wayland playback

- **Status:** Implemented. libmpv is a required dependency on Linux.
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
| Linux, Qt would run on Wayland (`QT_QPA_PLATFORM` unset with `WAYLAND_DISPLAY` set, or `QT_QPA_PLATFORM` starting with `wayland`), and libmpv, python-mpv and `PyQt6.QtOpenGLWidgets` load | mpv render engine | left as it is, so Qt uses Wayland |
| Linux X11, or `QT_QPA_PLATFORM=xcb` | `VlcPlayer` | `xcb` |
| libmpv missing on a Wayland session (a source run without it) | `VlcPlayer` | `xcb`, and a log line says why |
| Windows, macOS | `VlcPlayer` | unchanged |

Settings > General > Playback engine offers Automatic (the table above), mpv, or VLC on Linux. It is saved as `player_engine` and read by `main()` before `QApplication`, so a change applies at the next start; the dialog says which engine is running and whether a restart would change it. mpv chosen on X11 draws through the same OpenGL widget. `TVHPLAYER_ENGINE=vlc` or `TVHPLAYER_ENGINE=mpv` overrides the setting for one launch. `core/engine.py` makes the choice and `main()` logs it with the reason.

With libvlc, `main()` sets `QT_QPA_PLATFORM=xcb` whenever Qt would otherwise pick Wayland, including when the user set `wayland` themselves: libvlc 3 cannot embed into a Wayland window. It never forces `xcb` for mpv, which would put the UI back on XWayland.

### Video widget

The mpv path does not use `video_frame` as a native X11 window.

- The picture surface is a `QOpenGLWidget` in `player_container`, with the same focus policy, accessible name, and context menu as `video_frame`.
- Qt keeps painting that widget. `_show_playback_wait()` and `_protect_video_surface()` must not call `setUpdatesEnabled(False)` on it. The idle splash and spinner stay sibling overlays on `player_container`.
- The framebuffer size passed to mpv is the widget size multiplied by `devicePixelRatio()`, the same role `gdk_surface_get_scale_factor()` plays in Celluloid.
- The spinner and the fullscreen control bar stop being separate native windows. Over libvlc's native window only another native window shows on top, so the spinner is a native child and the bar is a frameless `Tool` window placed in screen coordinates. Over the GL widget both are plain children. This matters on Wayland, where a client cannot place its own top-level window, so the old bar would land wherever the compositor put it.
- The window's event filter drops paint events on `video_frame` while libvlc plays. It must not do that to the GL widget.
- Mouse and keyboard stay with Qt. `VlcPlayer` already turns off libvlc mouse and key grabbing for that reason. mpv has no video window to grab them.

`Player.attach(window_id)` cannot describe this. A window id is what `set_xwindow()`, `set_hwnd()`, and `set_nsobject()` consume. The mpv engine needs the OpenGL widget, a repaint when a frame is ready, and the current framebuffer during that paint. `VlcPlayer.attach(winId)` stays for the libvlc path. The window branches on which engine it constructed. The shared `play`, `stop`, `is_playing`, volume, mute, and handler methods stay as they are.

### Render loop

1. Create one mpv handle and one render context for the life of the engine. Load the next URL with `loadfile` on that handle. Do not destroy the render context on stop or on a channel change.
2. Create the render context on the widget's GL thread, with the widget context current. Pass `MPV_RENDER_API_TYPE_OPENGL`, and look up GL functions through `QOpenGLContext.getProcAddress()`. On Wayland, pass a `wl_display` as `MPV_RENDER_PARAM_WL_DISPLAY`. PyQt6 does not wrap `QNativeInterface::QWaylandApplication`, so Qt's own display is out of reach from Python. The widget opens a second connection with `wl_display_connect(NULL)` and keeps it until the render context is freed. mpv uses it only to open VA-API; frames still reach Qt's context as dma-bufs. Without any display, mpv's VA-API probe fails and decoding falls back to `vaapi-copy`.
3. mpv's render-update callback schedules work on the Qt thread. If the update includes a new frame, the widget repaints.
4. The widget's paint reads the bound framebuffer and calls `mpv_render_context_render()` with that framebuffer, the pixel size, and the Y flip mpv's OpenGL renderer requires.
5. Hardware decoding is requested with `hwdec=auto-safe`. The `wl_display` parameter is what makes that import possible. If the driver cannot import, mpv falls back inside the same context. Playback still has a picture.

`QApplication` sets `LC_NUMERIC` from the desktop, and libmpv refuses to start unless it is `C`. The engine resets it after `QApplication` exists and before creating the mpv handle.

The widget frees the render context, with its GL context current, when that context sends `aboutToBeDestroyed`, and creates a new one in the next `initializeGL`. The engine's `close()` frees it before `terminate()`.

Stop sets mpv's idle state and tells the window that playback stopped. The render context and the GL widget remain. The next `play()` loads another URL into the same context. That is the cycle the Wayland subsurface module crashes on, and this engine does not allocate a subsurface.

The first `playback-restart` after each `loadfile` maps to `on_playing`. `end-file` with reason `eof` or `stop` maps to `on_stopped`, and with reason `error` to `on_error`. Replacing a playing channel also ends the old file with reason `stop`; the window already ignores a stop while a channel is starting or playing. End of a recording and an open failure still reach the handlers the splash already uses. Events arrive on mpv's thread. `schedule` continues to hop them onto the Qt thread.

### Proxy and audio

mpv reads streams through FFmpeg, which honors `no_proxy` but has no rule that a server on this machine is always reached directly. The engine therefore also hides `http_proxy` from the process and sets mpv's `http-proxy` option for each URL from `proxy.stream_proxy()`: empty for loopback hosts and hosts in `no_proxy`, the saved proxy otherwise. That is the same decision requests sessions and ffmpeg children already get.

Audio output is mpv's default. The Flatpak manifest already has `--socket=pulseaudio`.

### Packaging

- Runtime dependency on Linux: `libmpv.so.2` (mpv 0.41 or another build with client API 2 and the render API). The Python binding is `python-mpv`, alongside `python-vlc`.
- Debian `Depends: python3-mpv` and RPM `Requires: python3-mpv`; each pulls in libmpv. pip and `requirements.txt` require `mpv`.
- Flatpak: one FFmpeg serves libmpv, libvlc, and the `ffmpeg` command used for local recordings. libvlc moves from 3.0.21 to 3.0.24, which uses FFmpeg 8.1 itself (Debian builds it against 7.1 unpatched), and FFmpeg moves from 4.4.5 to 8.1.3; mpv 0.41 needs 6.1 or newer. libass, libplacebo and libmpv are built as in Celluloid's Flathub manifest, without the parts a TV player does not use (Lua and JavaScript scripting, the `mpv` command, libopenmpt, rubberband, uchardet). The KDE 6.8 SDK already has fribidi, harfbuzz, libva (with Wayland), dav1d, Vulkan, shaderc and lcms2.
- Windows and macOS packages do not gain libmpv in this pass. They keep `VlcPlayer`.
- Do not build or ship the unmerged libvlc fork.

### Out of scope

- Replacing `VlcPlayer` on X11, Windows, or macOS.
- Qt Multimedia. It can also draw inside Qt, and it is a different decoder and buffering stack. This proposal is the mpv render path.
- A GTK `GtkGraphicsOffload` equivalent. Celluloid can promote its GL area to a Wayland subsurface, and that setting defaults to off. The first version renders into the widget framebuffer.
- Changing channel lists, DVR, or the built-in server.

## Test plan

Automated: `tests/test_engine.py` (the choice), `tests/test_mpv_player.py` (event mapping, proxy per stream, tracks, deinterlace, close order, and a run against the installed libmpv when there is one), and a window test that the mpv engine gets plain overlays and that Qt keeps painting the video widget.

On a Wayland session with `libmpv.so.2` present and `QT_QPA_PLATFORM` unset:

- The process platform is Wayland. `xcb` was not forced.
- The first channel shows a picture inside the player pane. The splash hides when playback starts.
- Changing channel while a picture is up replaces the picture and leaves the window up.
- Stop shows the splash and "Playback stopped". The next channel, or a recording, plays again. The process does not exit.
- A recording that reaches the end shows the splash. Playing something afterwards works.
- At 125% or 150% scale the controls and the picture stay sharp.
- Mute, volume, fullscreen, and the video context menu still work. Qt receives the keys.
- In fullscreen the control bar appears at the bottom of the picture, and the spinner covers the picture while a channel starts.
- The log shows `Using hardware decoding (vaapi)`, not `vaapi-copy`, on a VA-API driver.
- With `http_proxy` set, the built-in server's streams still connect directly.

On an X11 session, and on Wayland with `QT_QPA_PLATFORM=xcb` already set, or with `libmpv` absent:

- `VlcPlayer` is used and the current embedding behavior is unchanged.

Windows and macOS builds are unchanged.
