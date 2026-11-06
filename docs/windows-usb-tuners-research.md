# Windows USB tuner research

Research date: 2026-11-06. This is an architecture recommendation, not an implemented or RF-tested feature.

## Findings

The current WSLc backend cannot obtain a USB tuner by adding firmware packages or a bind mount to its Debian image. Normal WSL distributions and WSLc sessions are different environments. USB attached using `usbipd attach --wsl` is not automatically available in the WSLc session.

The installed WSL 3.0.3 `wslc run --help` offers GPU forwarding, filesystem mounts and network publishing, but no generic `--device`, USB forwarding or privileged-container option. Microsoft's USB passthrough feature request remains open. Its October 9 maintainer response assigns it for evaluation; it does not announce a supported implementation.

Sources:

- [Microsoft WSL USB guide](https://learn.microsoft.com/en-us/windows/wsl/connect-usb)
- [WSLc USB feature request](https://github.com/microsoft/WSL/issues/41031)
- [Microsoft WSLc backend guidance](https://github.com/microsoft/mxc/blob/main/docs/backends/wslc/wsl-container-getting-started.md)
- [WSLc settings](https://learn.microsoft.com/en-us/windows/wsl/wsl-container-settings)
- [WSLc session API](https://wsl.dev/api-reference/c/session-apis/)

## Evidence from this machine

- Windows enumerates `USB\VID_0572&PID_C68A\161206` as `EyeTV Stick` with ConfigManagerErrorCode 28 and no Windows driver service.
- Linux's supported-device list identifies `0572:c68a` as MyGica Mini DVB-(T/T2/C) USB Stick T230C v2.
- Installed WSL reports version 3.0.3.0 and kernel 6.18.54.1.
- A read-only check in the WSL system distribution reports:

```text
CONFIG_MODULES=y
CONFIG_MEDIA_SUPPORT=m
CONFIG_MEDIA_DIGITAL_TV_SUPPORT=y
CONFIG_DVB_CORE=m
CONFIG_MEDIA_USB_SUPPORT=y
# CONFIG_DVB_USB_V2 is not set
# CONFIG_MEDIA_TUNER_SI2157 is not set
CONFIG_USBIP_VHCI_HCD=m
```

No dvbsky, si2168 or si2157 module files were found under its `/lib/modules`. This checks the normal WSL kernel, not an assertion about every WSLc session kernel. No USB device was attached, driver installed, kernel replaced or global configuration edited during research.

[Linux supported-device list](https://www.kernel.org/doc/html/v5.14/admin-guide/media/dvb-usb-dvbsky-cardlist.html)

## Recommended architecture

Use an app-managed **normal WSL2 distribution** for the USB backend. Run Tvheadend directly inside that distribution, with persistent settings and recordings. Retain WSLc for the existing IPTV and network-tuner backend. Select the backend explicitly and migrate settings deliberately: do not run two servers against one live configuration directory.

Proposed path:

```text
Windows USB tuner
  -> usbipd-win (share selected device)
  -> normal WSL2 VM (USB/IP + Linux DVB drivers)
  -> /dev/dvb/adapterN
  -> Tvheadend in an app-owned WSL distribution
  -> Windows TVHplayer
```

This is a recommendation derived from the supported WSL USB path and current WSLc restrictions, not an end-to-end validated implementation.

Install usbipd-win through an explicit setup action. Sharing a selected device with `usbipd bind --busid ...` requires administrator privileges; ordinary attachment subsequently does not. Track the selected device's identity and ownership, reconnect on unplug/replug and resume, and detach only devices this app attached. Do not select unrelated devices automatically. Windows applications cannot use a device while it is attached to WSL.

[usbipd-win WSL lifecycle documentation](https://github.com/dorssel/usbipd-win/wiki/WSL-support)

Putting a SAT>IP bridge in normal WSL and keeping Tvheadend in WSLc is another possible design. It adds a service, discovery/control and stream routing across the WSL/WSLc boundary. Prototype only if keeping one WSLc Tvheadend is a firm requirement; it does not remove the Linux driver problem. Running Tvheadend directly beside the tuner is the simpler first prototype.

## Driver support belongs to the VM kernel

A Debian container/rootfs does not choose the running WSL kernel. Installing Debian `linux-image-*` inside a rootfs does not make WSL boot it. Firmware in `/lib/firmware` supplies device code but does not replace missing kernel modules.

For the MyGica driver chain, investigate and enable `CONFIG_DVB_USB_V2`, `CONFIG_DVB_USB_DVBSKY`, `CONFIG_DVB_SI2168`, and `CONFIG_MEDIA_TUNER_SI2157`, with their I2C, USB and media dependencies. The dvbsky source connects the USB bridge to Si2168 and Si2157-family drivers. Silicon revisions determine the exact firmware requested; confirm it from probe/tuning logs.

- [Upstream dvbsky driver](https://raw.githubusercontent.com/torvalds/linux/master/drivers/media/usb/dvb-usb-v2/dvbsky.c)
- [Si2168 firmware names](https://raw.githubusercontent.com/torvalds/linux/master/drivers/media/dvb-frontends/si2168_priv.h)
- [Si2157-family driver](https://raw.githubusercontent.com/torvalds/linux/master/drivers/media/tuners/si2157.c)
- [Microsoft kernel configuration](https://raw.githubusercontent.com/microsoft/WSL2-Linux-Kernel/linux-msft-wsl-6.18.y/arch/x86/configs/config-wsl)

Use this order for driver provisioning:

1. Detect the running kernel, configuration, matching module tree and driver aliases. Use inbox modules when available.
2. Investigate building the missing in-tree media modules against the exact installed Microsoft kernel release/configuration and exported symbols. Verify dependency loading and ABI compatibility on each supported WSL release. Shipping arbitrary Debian modules will not work. This route needs a feasibility experiment before being selected for production.
3. If matching add-on modules cannot provide a reliable driver stack, a custom Microsoft-derived WSL kernel plus its matching modules image is the documented fallback. Preserve Microsoft's baseline settings and enable a broad set of upstream DVB USB bridges, frontends and tuners.

The custom-kernel fallback has a product consequence: ordinary WSL's `.wslconfig` kernel and kernelModules settings affect the VM powering all WSL2 distributions. An app-owned distribution does not isolate its kernel. Therefore do not silently change the user's kernel or shut down their WSL workloads. A production design requiring an independent kernel should evaluate a dedicated VM instead, including the extra USB forwarding and lifecycle work that entails.

- [WSL kernel build and modules-image instructions](https://github.com/microsoft/WSL2-Linux-Kernel)
- [Global WSL kernel settings](https://learn.microsoft.com/en-us/windows/wsl/wsl-config)

## Root filesystem and firmware requirements

Build a separate WSL rootfs artifact from the pinned Tvheadend sources and user-space dependencies. The existing OCI archive should not be assumed to be directly importable as a WSL rootfs. Include `kmod`, `usbutils`, DVB inspection tools such as `dvbv5-utils`, and a device-event/firmware-loading setup tested in normal WSL.

Maintain a pinned firmware inventory for supported tuner families, including the Si2168 and Si2141/Si2157-family firmware required by actual tested revisions. Verify file presence and hashes during the build. Review redistribution terms for each blob and preserve notices; do not assume `firmware-misc-nonfree` contains every DVB firmware file. Firmware must be installed in the environment that services the driver's firmware requests, before device probing/tuning.

[Debian firmware/driver inventory](https://wiki.debian.org/Firmware/List)

Broad support requires both a broad tested kernel-module set and matching firmware. Publish a USB-ID compatibility matrix with tested WSL/kernel/firmware versions rather than claiming all Linux-supported tuners work automatically.

## First feasibility milestone

Before changing the application backend, demonstrate this physical dongle in a disposable normal WSL2 distribution:

1. Provide the matching DVB module stack and firmware; attach only the chosen dongle through usbipd-win.
2. Confirm USB enumeration, module binding, successful firmware loading and creation of `/dev/dvb/adapterN/frontend0`, demux and DVR nodes.
3. Confirm DVB-T2 delivery-system support, RF lock, scanning and a playable transport stream with the user's aerial and local multiplex.
4. Run Tvheadend, map services and play/record through the Windows app.
5. Check sustained recording, transport errors, unplug/replug, suspend/resume, reboot, competing Windows use and restoration after detach.
6. Repeat with representative dvbsky, em28xx, rtl28xxu and other supported families before expanding compatibility claims. RF use must be coordinated with ongoing viewing/recording.

Success at `lsusb` alone is insufficient. The release gate is reliable tuning, streaming and recovery with the intended kernel/module/firmware combination.
