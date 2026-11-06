# TVHplayer on Windows: USB Tuner Support Without a Custom WSL Kernel

**Architecture decision proposal**  
**Date:** 2026-11-07  
**Status:** Proposal / research-informed; no end-to-end USB-tuner prototype verified  
**Project:** https://github.com/mfat/tvhplayer

## 1. Executive summary

TVHplayer currently packages a built-in TVHeadend server for Windows using **WSL Containers (`wslc.exe`)**. The Windows application and its TVHeadend container can use network-accessible sources, including IPTV and HDHomeRun. However, conventional USB television tuners connected to Windows are not automatically exposed as Linux DVB devices inside that container.

**Architecture constraint:** TVHplayer must not modify the globally configured WSL kernel or require the user to accept an application-specific kernel affecting other workloads. A regular WSL distribution, or Docker inside WSL2, does not independently solve that constraint: Linux DVB driver support still comes from the host kernel. Moreover, Microsoft's documented `.wslconfig` kernel setting is global to WSL2 *distributions* and explicitly does **not** apply to WSL Containers; do not assume it can configure WSLc. [1]

**Preferred direction:** Keep USB tuner drivers and RF tuning on **Windows**, and translate the hardware into a **network tuner** that TVHeadend can use from WSLc. Prioritize **SAT>IP**, because it carries tuner control as well as transport streams and accommodates terrestrial, cable and satellite DVB systems. Consider HDHomeRun emulation as a secondary protocol and simple IPTV streaming as an initial feasibility test.

**Recommended development path:**

1. Prove Windows BDA capture with **TSDuck** against real hardware.
2. Prove WSLc TVHeadend interoperates with a known working external SAT>IP server (for example, DVBViewer Media Server) without relying on multicast discovery.
3. Examine **SatPI** virtual tuner / RTSP source code to assess whether its frontend can be adapted to send tuning commands to a Windows BDA controller.
4. Prototype **Windows BDA capture + SAT>IP control/streaming** with one physical tuner.
5. Choose between an adapted SatPI server and a small TVHplayer-owned SAT>IP frontend based on measured integration complexity, licensing and reliability.

**Recommendation is conditional:** No ready-to-embed, maintained, open-source Windows BDA-to-SAT>IP server has been established in this research. The main unknown is the effort to map dynamic SAT>IP tuning and session operations to BDA through TSDuck or another capture layer.

## 2. Current implementation and the problem

### 2.1 What the existing code does

The following paths were inspected in the TVHplayer repository in the preceding technical review (main-branch snapshot during this discussion):

- [`tvhplayer/core/windows_wslc.py`](https://github.com/mfat/tvhplayer/blob/main/tvhplayer/core/windows_wslc.py): builds a `wslc run --detach` command; publishes HTTP/HTSP ports, adds UDP ports for the HDHomeRun return path and mounts configuration and recording storage. No USB/DVB `--device` equivalent is in the observed `launch()` command.
- [`tvhplayer/wslc_builtin_supervisor.py`](https://github.com/mfat/tvhplayer/blob/main/tvhplayer/wslc_builtin_supervisor.py): manages container startup, readiness, port retries and HDHomeRun transport configuration.
- [`windows/backend/Containerfile`](https://github.com/mfat/tvhplayer/blob/main/windows/backend/Containerfile): builds the Debian-based runtime image for TVHeadend.
- [`tvhplayer/core/tuners.py`](https://github.com/mfat/tvhplayer/blob/main/tvhplayer/core/tuners.py) and [`tvhplayer/core/tvh_admin.py`](https://github.com/mfat/tvhplayer/blob/main/tvhplayer/core/tvh_admin.py): read TVHeadend's hardware tree once hardware is visible to the server.
- [`windows/backend/README.md`](https://github.com/mfat/tvhplayer/blob/main/windows/backend/README.md): describes network tuner discovery and Windows HDHomeRun handling.

**Scope note:** This is not an exhaustive audit of every commit or code path. Revalidate the branch and code before implementing.

### 2.2 Desired user experience

A user installs TVHplayer on Windows, plugs in a supported USB DVB-T/T2, DVB-C or DVB-S/S2 tuner, and selects it in TVHplayer. TVHeadend discovers an appropriate frontend, scans muxes, discovers services, records and streams channels **without** the user installing a Linux kernel, USB/IP stack, Docker Desktop, a complete separate Linux VM, or configuring manual per-channel IPTV endpoints. Supported hardware depends on available Windows drivers and verified capture capability.

### 2.3 Why simple stream forwarding is insufficient

An MPEG-TS UDP or HTTP stream answers *what packets are available*, not *which frequency or modulation should the device tune*. For TVHeadend to perform normal mux scanning, a network tuner bridge must accept and execute tuning commands, control tuners, report readiness/errors and deliver the corresponding MPEG-TS. That is the value of a SAT>IP or compatible tuner protocol.

### 2.4 Non-negotiable constraints

- Do not modify `%UserProfile%\.wslconfig` or install a replacement globally shared WSL2 kernel.
- Keep the existing WSLc server viable for IPTV/HDHomeRun/network sources; USB support is opt-in.
- Never seize or reconfigure all connected USB devices automatically.
- Require explicit consent for driver installation, elevated privileges, firewall changes or persistent services.
- Do not claim device compatibility without testing the Windows capture path and actual TVHeadend playback/recording.
- Do not silently expose local tuner control or streaming endpoints to the LAN.

## 3. Candidate architectures

### Option A — Windows BDA → SAT>IP → existing WSLc TVHeadend (preferred)

```text
USB DVB tuner
    |
Windows manufacturer's BDA driver
    |
Windows tuner bridge (capture/tuning/session management)
    |       RTSP/SAT>IP controls and MPEG-TS over RTP/UDP or interleaved TCP
    +------------------------------------------------------------+
                                                                 |
                                                  WSLc TVHeadend SAT>IP client
                                                                 |
                                                  TVHplayer channel/DVR interface
```

**Benefits:** No Linux USB driver or WSL kernel modification; preserves existing WSLc deployment; TVHeadend can manage mux tuning/scanning; accommodates different DVB families where BDA capture supports them. Can ultimately serve remote TVHeadend instances if deliberately enabled.

**Challenges:** Dynamic RTSP-to-BDA tuning translation; RTSP setup/teardown, transport/payload details, PID selection, signal-lock feedback; shared mux sessions and per-physical-tuner arbitration; satellite DiSEqC/voltage/tone and vendor extensions; WSLc-to-Windows endpoint reachability.

**Preferred transport for first test:** Test interleaved RTP over RTSP/TCP if accepted by both endpoints; it can simplify crossing the container boundary. Do not assume it eliminates all control and address-routing issues. Provide a directly configured SAT>IP descriptor or address if SSDP discovery cannot cross the boundary. Validate against the specific TVHeadend build.

**Recommendation:** Main product architecture, subject to proof of concept.

### Option B — Windows BDA → HDHomeRun emulation → WSLc TVHeadend

**Benefits:** TVHeadend already supports HDHomeRun; TVHplayer currently contains Windows-specific HDHomeRun discovery and UDP return-path handling.

**Limitations:** Implementing device discovery, HDHomeRun control endpoints and expected protocol semantics remains substantial work; not a general-purpose match for DVB-S/S2 satellite functionality. A Windows USB DVB tuner is not automatically compatible with HDHomeRun control or scanning semantics. The prior HDHomeRun NAT/UDP return-path issue may recur.

**Recommendation:** Secondary option for carefully defined DVB-T/T2 and DVB-C hardware, or if a reusable HDHR emulator implementation proves markedly simpler. Not the default universal bridge.

### Option C — Windows BDA → MPEG-TS HTTP/UDP → TVHeadend IPTV input

**Benefits:** Fastest narrow proof that a Windows USB device can tune and deliver decodable MPEG-TS into WSLc. Can be useful as a fallback when a third-party tuner application already exports fixed channel streams.

**Limitations:** Does not expose a controllable physical frontend or support TVHeadend's native RF mux scanning by itself; changing frequency must be handled through an out-of-band controller or predefined channel mapping.

**Recommendation:** Phase-0 proof of the capture/network boundary; not a complete replacement for SAT>IP.

### Option D — External commercial Windows tuner server

Use **DVBViewer Media Server** as an independently installed BDA-to-SAT>IP provider, or as a reference implementation in a lab.

**Benefits:** Established Windows tuner/SAT>IP product; can prove end-to-end interoperability before bridge development.

**Limitations:** Proprietary licensing and distribution; cannot assume permission to bundle, relicense or modify. Product-specific setup, license and support burden.

**Recommendation:** Excellent test oracle and optional user-selected external backend; not the default embedded implementation.

### Option E — WSL2 distribution/Docker + custom kernel or USB/IP device passthrough

**Benefits:** Potential direct `/dev/dvb` access on systems with working USB/IP and compatible DVB drivers; conventional Linux TVHeadend workflow.

**Disqualifier for default product:** The custom WSL2 kernel configuration is shared across WSL2 distributions; Docker containers share their Linux host kernel. WSLc is a distinct environment to which ordinary `.wslconfig` settings do not apply. USB passthrough, driver/firmware coverage and user-environment impact remain serious issues. [1]

**Recommendation:** Exclude as default implementation under the stated no-global-kernel-change requirement. A separately managed full VM with its own kernel could be an advanced escape hatch, at greater cost and complexity.

### Option F — Native Windows TVHeadend with a BDA backend

**Benefits:** Eliminates WSL network/container boundary and potentially reduces installed infrastructure.

**Limitations:** Requires maintaining a Windows TVHeadend port, driver-facing BDA capture integration and platform-specific lifecycle testing; very large scope.

**Recommendation:** Long-term exploration only.

## 4. Existing building blocks and their limitations

| Candidate | Verified relevant capability | Missing capability for a finished Windows bridge | Licensing/integration position | Role |
|---|---|---|---|---|
| **DVBViewer Media Server** | Windows tuner management and SAT>IP server feature | Source integration is not available as a normal open-source dependency | Proprietary; verify current EULA and redistribution terms | External interoperability oracle |
| **TSDuck** | Windows BDA tuner capture, MPEG-TS processing, network outputs; C++ library/plugin surface | Complete SAT>IP control server and physical tuner arbitration | Open source; inspect exact licenses of bundled components/build | Preferred capture layer |
| **SatPI** | Linux SAT>IP server; RTP/AVP and RTP/AVP/TCP; FILE, STREAMER, CHILDPIPE virtual tuners | Windows BDA tuning bridge; prove dynamic request mapping and operating-system feasibility | Open source; confirm license obligations before distributing modified work | Preferred SAT>IP adaptation candidate |
| **Minisatip** | Mature Linux SAT>IP server | Replace/adapt Linux DVB-oriented hardware integration with Windows controller | Verify upstream and dependency licensing for chosen revision | SAT>IP alternative |
| **NextPVR / MediaPortal** | Windows TV-tuner-server ecosystems | A reusable, independently verified generic SAT>IP export implementation was not established | Review project-specific licensing and plugin ecosystem | Possible integration alternatives, not proven bridge |

**Important evidence boundary:** SatPI's documentation confirms virtual stream/pipe inputs, but that alone **does not prove** that dynamic RF tune requests are passed to the source or that it can become a BDA-controlled SAT>IP tuner without source modifications. This is the principal code-review gate. [2][3]

### Why TSDuck?

TSDuck is actively documented for Windows; the build documentation says DVB tuners are supported on Windows and Linux. It provides the operating-system-specific capture functionality that is costly to replicate independently. It does not provide a verified turnkey SAT>IP server. [4][5]

### Why SatPI?

SatPI explicitly documents SAT>IP serving, RTP over UDP/TCP and virtual `STREAMER`/`CHILDPIPE` inputs. Those are useful starting points for an adapter. But the Windows porting effort and semantics of dynamic tuning must be measured, not assumed. [2][3]

## 5. Architecture proposals for implementation

### Proposal 1 — Native Windows bridge with TSDuck + reusable SAT>IP protocol layer

Deploy a small Windows helper bundled with TVHplayer. The helper exposes local SAT>IP and controls a BDA tuner through TSDuck or an equivalent BDA wrapper. TVHeadend connects through the available Windows-to-WSLc network path.

- **Pro:** One Windows-side process controls capture, sessions and streaming; no additional SAT>IP service in the Linux container; fewer inter-process network hops; cleaner future standalone use.
- **Con:** SAT>IP protocol work may be substantial unless a suitable portable library/implementation can be reused.
- **Decision rule:** Choose if SatPI is prohibitively Linux-specific or requires a large rewrite to integrate Windows BDA control.

### Proposal 2 — Windows TSDuck capture service + adapted SatPI SAT>IP frontend

Keep BDA capture on Windows. Run SatPI on the host **if a practical Windows port is proven**, or in a separate reachable process near TVHeadend. Extend its virtual tuner so RTSP tune commands are translated into explicit requests to the Windows capture controller; feed MPEG-TS back over a bounded, authenticated local transport.

- **Pro:** Potentially substantial reuse of session/RTSP/RTP/SSDP logic.
- **Con:** Linux portability and virtual-input tuning semantics are unknown until source review. Additional failure boundary between capture and protocol layers. GPL compliance must be planned where relevant.
- **Decision rule:** Choose only if a small source spike proves dynamic retuning, cancellation and streaming without architectural surgery.

### Proposal 3 — External SAT>IP provider integration first

Allow the user to select an existing installed Windows SAT>IP provider, especially DVBViewer Media Server, then configure TVHeadend's SAT>IP connection. Continue developing the open-source native bridge separately.

- **Pro:** Fast route to useful functionality and a realistic interoperability benchmark.
- **Con:** Extra installation, license and third-party lifecycle complexity; not the desired self-contained solution.
- **Decision rule:** Offer as optional early-access integration, not the final embedded architecture.

### Proposed stable internal abstraction

Separate **device capture** from **network tuner serving**:

```text
DeviceCatalog: discover(), capabilities(), stable_identity()
CaptureBackend: open(), tune(delivery_system, frequency, params), start_ts(), stop(), signal_status()
TunerScheduler: reserve(), share_mux(), release(), handle_disconnect()
NetworkTunerFrontend: advertise(), session_setup(), retune(), pid_update(), stream(), teardown()
BridgeSupervisor: start(), health(), recover(), stop()
```

The interface names are illustrative rather than a required API. Define normalized tuning parameters and return structured unsupported/timeout/driver errors. Make capture and frontend replaceable (SAT>IP first, HDHomeRun optionally later).

## 6. Risks, safeguards and compatibility

1. **Windows BDA differences.** Vendor drivers vary; enumerate capabilities and test specific devices, including firmware, modulation systems and satellite-control features. Never advertise delivery systems the selected tuner cannot actually tune.
2. **Session sharing.** One RF frontend normally tunes one multiplex at a time. Multiple programs from the *same mux* can be shared; simultaneous unrelated muxes require additional tuners. Reject resource conflicts predictably.
3. **PID selection.** Support SAT>IP PID requests and updates correctly. Test full-MPTS vs filtered output and PAT/PMT behavior before optimization.
4. **WSLc network boundaries.** Validate Windows-host address reachability, advertised RTSP URLs, container-initiated connections and RTP return routing. Prefer explicitly configured endpoints over multicast dependence when necessary.
5. **Security.** Bind control ports to a verified local-only interface where possible; otherwise constrain connections using firewall rules/ACL and explicit setup. Do not inadvertently expose raw transport streams or control endpoints to an entire LAN.
6. **Licensing.** TSDuck, SatPI, Minisatip, capture dependencies and any reused protocol code must be reviewed individually. Avoid copying proprietary DVBViewer implementations; use its documented external behavior only for interoperability testing.
7. **Power/hotplug.** USB devices can reset or move bus locations after sleep, replug or updates. Match stable device identity where possible; expire stale sessions; provide reconnect UI and diagnostics.
8. **Resource usage.** Bound memory queues and monitor MPEG-TS continuity, backpressure, startup latency and long-running recordings.
9. **Service ownership.** Start the helper only when selected and needed; distinguish a user-installed SAT>IP server from a TVHplayer-owned helper; never terminate unrelated services.
10. **No DRM circumvention.** Limit capture to legally accessible streams supported by the user's hardware and rights; do not add conditional-access bypass.

## 7. Phase plan and acceptance gates

### Phase 0 — Baselines, hardware matrix and reproducibility

- Select at least one known-working BDA USB tuner (preferably DVB-T/T2 first) and a known-good mux/frequency.
- Record device vendor/product IDs, Windows driver, delivery systems, Windows version, current WSLc and TVHeadend versions.
- Establish a reproducible TVHeadend backend launch and basic IPTV/HDHomeRun regression.
- **Pass:** Both Windows and TVHeadend baselines are documented, with stable channels on an existing network source.

### Phase 1 — Validate known SAT>IP server into WSLc

- Use an external Windows SAT>IP server with real BDA hardware.
- Verify TVHeadend finds/configures a tuner through explicit discovery/descriptor registration if multicast fails.
- Test initial scan, retune, continuous live playback and recording.
- **Pass:** Repeated scan and 30-minute recording succeed, including reconfiguration/restart. If failure, resolve network/runtime compatibility before developing a new bridge.

### Phase 2 — Validate TSDuck BDA input

- Enumerate, select and tune the same USB device from TSDuck on Windows.
- Confirm stream validity (PAT, PMT, MPEG-TS continuity, nonzero throughput) and feed an IPTV/UDP stream into TVHeadend as a diagnostic.
- **Pass:** Reliable capture and playback from Windows hardware; document supported tuning params and failures.

### Phase 3 — SatPI source-level feasibility spike

- Trace RTSP tuning parse → frontend allocation → virtual input → stream output → teardown.
- Prototype a virtual frontend that accepts a *frequency change* and instructs the Windows TSDuck controller to retune.
- Check RTP/TCP interoperability and minimum required modifications; verify build/packaging/licensing approach.
- **Pass:** TVHeadend-initiated change between two real RF muxes retunes the hardware automatically, without manual stream reconfiguration. **Fail/stop:** Dynamic tuning cannot be added without extensive rewrite, or hosting/build/license costs exceed a native frontend alternative.

### Phase 4 — Choose and implement protocol frontend

- **Path 4A:** Adapt SatPI with a precise transport/control interface, if Phase 3 passes.
- **Path 4B:** Build a narrower native Windows SAT>IP frontend over the proven capture interface, if SatPI fails the gate.
- Add tuner lease arbitration, session teardown, PAT/PMT/PID handling, stream keepalive and structured diagnostics.
- **Pass:** Automated RF mux scan, channel switch, simultaneous same-mux consumers and deterministic busy errors for conflicting muxes.

### Phase 5 — Integrate with TVHplayer first run

- Detect BDA candidate devices and show driver/capture eligibility checks.
- Offer USB tuner integration explicitly; explain opt-in helper installation and firewall changes.
- Start and supervise only TVHplayer-owned helper processes; configure TVHeadend's SAT>IP frontend via its normal APIs.
- Preserve current WSLc server state/ports/recordings and do not modify global WSL kernel settings.
- **Pass:** A fresh Windows install can set up the supported tuner with no command-line steps after standard driver installation; existing IPTV/network-tuner setups remain unaffected.

### Phase 6 — Production testing

- Multi-hour recording soak test; repeated scan, retune, suspend/resume, USB hot-unplug/replug, WSLc restarts and Windows firewall/network-profile changes.
- Test multiple hardware classes (DVB-T/T2, DVB-C, DVB-S/S2), keeping documented limitations rather than promising universality.
- Add per-tuner support logs and a one-click diagnostic export without secrets.
- **Pass:** Tested compatibility matrix, predictable error recovery and regression coverage for existing network sources.

## 8. Open engineering questions / research backlog

**Highest priority:**

1. Can SatPI's `STREAMER`/`CHILDPIPE` virtual frontend *receive and execute arbitrary RF tuning changes*, or are inputs limited to fixed/transformed streams? Locate exact classes and call graph before deciding.
2. Can SatPI build and run natively on Windows with acceptable effort? If not, what concrete IPC path is required when SatPI remains on the Linux side?
3. Can TSDuck BDA operations be controlled reliably as a long-lived C++ service, or is it safer to spawn a new capture process for each tune? Measure latency, PID reconfiguration and cleanup.
4. Can the existing TVHeadend build reliably consume RTSP/RTP-over-TCP from a host-side SAT>IP server through WSLc? Test actual packets and routing.
5. What restricted local-network binding and security model works with WSLc's host connectivity?

**Additional:** DVB-S/S2 DiSEqC and LNB control, actual standards compliance vs TVHeadend-specific behavior, hardware classification, licenses of linked binaries, and how to avoid interference with third-party programs currently holding a tuner.

## 9. Decision and non-goals

### Proposed architecture decision

- **Approve Phase 0–3 investigation** with no irreversible platform changes.
- **Prefer Windows BDA capture feeding SAT>IP** as the product solution.
- **Do not select SatPI for production until the dynamic retune spike succeeds.** Maintain a fallback of a native SAT>IP frontend built around TSDuck capture.
- **Keep HDHomeRun emulation secondary** and IPTV transport as a diagnostic/fallback.
- **Reject global WSL custom-kernel changes** as part of the standard user experience.

### Explicit non-goals for initial release

- Supporting every USB tuner and every proprietary satellite control extension.
- Adding automatic decryption/conditional access handling.
- Replacing TVHeadend or the current WSLc backend.
- Building a general-purpose Windows television server for arbitrary LAN consumers.
- Installing kernel drivers, global WSL settings or changing unrelated software configurations.

## 10. References

1. Microsoft Learn, **Advanced settings configuration in WSL** — global `.wslconfig` behavior, WSL Containers distinction, custom kernel settings. https://learn.microsoft.com/en-us/windows/wsl/wsl-config
2. SatPI repository README — supported SAT>IP features, RTP/AVP/TCP and virtual tuner inputs. https://github.com/Barracuda09/SATPI/blob/master/README.md
3. SatPI wiki, **Virtual tuners explained** — `CHILDPIPE`, `STREAMER`, FILE input and translation requirements. https://github.com/Barracuda09/SATPI/wiki/Virtual-tuners-explained
4. TSDuck user guide — Windows DVB tuner input, TS processing and plugin architecture. https://tsduck.io/docs/tsduck.html
5. TSDuck build guide — supported platforms and Windows/Linux DVB support. https://tsduck.io/docs/tsduck-build.html
6. DVBViewer Media Server product information — Windows server and SAT>IP capability (verify current license separately). https://www.dvbviewer.com/en/index.php?page=dms
7. Minisatip source repository — alternate SAT>IP implementation. https://github.com/catalinii/minisatip
8. TVHplayer source: https://github.com/mfat/tvhplayer

---

**Bottom line:** A Windows-hosted SAT>IP bridge appears better aligned with TVHplayer's self-contained WSLc architecture than custom-kernel/Docker-based USB passthrough. TSDuck offers promising BDA capture reuse; SatPI offers promising SAT>IP protocol reuse. Neither is confirmed to be a turnkey Windows BDA-to-SAT>IP bridge, so the gating experiment is TVHeadend-driven *real hardware retuning* across the bridge.
