# UGNAY — LAN Health Checker interface

The default entry point now serves an HTML, CSS, and JavaScript authentication
interface based on the supplied Login, Sign up, and Guest designs. Animated
gradient backdrops and an SVG network map run locally, with no CDN dependencies.
The original desktop interface is available with `python main.py --desktop`.

## Web interface and authentication

Start the local application with Python 3.10 or newer:

```powershell
python main.py
```

Open **http://127.0.0.1:8000**. Use `#login`, `#signup`, or `#guest` to open a
specific authentication screen. An alternative port is supported with `--port 8080`.
Serve the frontend through Python; opening `web/index.html` directly cannot call
the authentication API. There are no new pip or npm dependencies.

SQLite creates `data/ugnay.sqlite3` automatically, including the roles,
role_permissions, users, and sessions tables. The database and its journal files
are ignored by Git. Back up the database with the server stopped. To choose a
different database, pass `--database path/to/ugnay.sqlite3` to each command.

Create your first administrator through the local terminal:

```powershell
python main.py --create-admin
```

Enter a username, email, and password when prompted. Passwords are hidden during
entry. No default credentials are installed. Public signup always creates a
regular user, regardless of fields submitted by the client.

| Role | Permissions |
| --- | --- |
| Guest | View the latest discovery results; temporary access for up to two hours |
| User | View results and run network discovery |
| Admin | User permissions plus list accounts, change user/admin roles, enable/disable accounts, and reset passwords |

The guest screen keeps the reference layout but disables the password field and
Remember me because guests do not need credentials. Guest names are optional;
a unique temporary account is created in SQLite. Expired guest records are
cleaned up when another guest session starts. Guests sign up for a separate
permanent account to gain discovery access.

Passwords use salted PBKDF2-SHA256 with 600,000 iterations and a 12–128 character
length requirement. Random session tokens are stored as SHA-256 hashes in SQLite.
Cookies are HttpOnly and SameSite=Strict. Ordinary logins have an eight-hour server
expiry and a browser-session cookie; Remember me uses a persistent cookie and a
30-day expiry. Closing a browser does not explicitly revoke a server-side session,
and some browsers restore session cookies. Log out to revoke the session.

Permissions are checked by the server for every privileged action. Mutations
require the local Origin and, for authenticated requests, a CSRF token. Login,
signup, and guest creation are rate-limited in server memory (10 requests per
name and 30 per client address per 10 minutes). Restarting clears those limits.
Role, status, and password changes revoke all sessions for the affected account.
An administrator cannot remove their own access or disable the last active admin.

Forgot password opens recovery guidance. An admin can reset a password from the
Account access panel. A person who manages the local installation can also run:

```powershell
python main.py --reset-password USERNAME
```

There is no email delivery or email-based recovery configured. The server binds
only to loopback and uses HTTP. It is intended for local use; public deployment
requires a production server, HTTPS with Secure cookies, and deployment-specific
security configuration. The legacy `--desktop` interface remains a separate,
unauthenticated local tool; web authentication does not protect direct OS or
database access.

After login, a small network workspace demonstrates the enforced permissions.
Its Scan network action calls the existing discovery service on a background
thread. No probes run at startup or on login. Results are shared by the local
server's users and held in memory; a server restart clears them. Existing desktop
ping and reporting screens have not been ported to the browser.

### Replace the placeholder graphics

`web/assets/` contains clearly named SVG placeholders for the logo, user, email,
lock, eye, network, chevron, and optional backdrop. Replace these files in place,
or update the paths in `web/index.html` and `web/styles.css`. The backdrop is
transparent by default so the CSS gradients remain visible; adjust
`.backdrop-placeholder` opacity for your replacement. The server serves SVG, PNG,
JPEG, WebP, and ICO files with simple filenames from this folder. The orbital map is inline SVG in
`web/index.html`; edit its paths and `animateMotion` durations there. Colors and
gradient motion are controlled by `web/styles.css`. Reduced-motion preferences
disable animations.

### Verify web authentication

```powershell
python -m unittest discover -s tests -p test_web_auth.py -v
```

These tests use a temporary SQLite database and a fake discovery service. They
cover registration, hashed credentials and session tokens, cookie lifetime,
login, logout, expiry, role escalation attempts, guest restrictions, CSRF/Origin
checks, admin changes, password recovery, rate limits, and persistence. They do
not scan the real network or create accounts in your application database.

## Original desktop interface

A runnable Python Tkinter interface based on the supplied Overview, Devices,
Ping tests, and Reports designs, with Windows IPv4 network detection and ICMP
device discovery. Detailed ping tests, statistics calculations, report generation,
recommendation analysis, and text export remain unimplemented service stubs.

For the complete Module 1 user guide, architecture, API reference, configuration,
error handling, verification history, and limitations, see
[Module 1: Network Discovery](docs/module-1-network-discovery.md).

## Run

Use Python 3.10 or newer with Tkinter installed:

```powershell
python main.py --desktop
```

There are no pip dependencies. The normal Windows Python installer includes
Tkinter. Keep `main.py`, `ugnay/`, and the supplied `icons/` folder together.
Icons use Tk's built-in PNG support; no Pillow dependency is needed. If an icon
is missing, its control still works with its text label. The `icons_svg/` folder
is the original design asset pack and is not needed at runtime.

## What works now

- Sidebar navigation between all four screens.
- Device tables, shared selection, device details, and status labels.
- Device and ping-count dropdowns (4, 10, or 20 requests).
- Displays for average/max latency, packet loss, individual replies, and timeouts.
- A small reply-latency chart drawn directly with Tkinter Canvas.
- Read-only report preview, report selection, and recommendations area.
- Busy states, empty tables, no-selection states, and error dialogs.
- Scrollable pages and result areas at smaller window sizes.
- A background-worker/UI-queue bridge for the future services.
- Windows local IPv4 detection using the adapter's actual subnet prefix.
- Concurrent ICMP device discovery, optional hostname lookup, and actual scan results.

The application starts with an undetected network, zero devices, no reports, and
a prompt to use **Scan Network**. Startup does not send probes or load sample
results. Scan Network reads the local Windows adapter configuration and discovers
ICMP responders in the detected subnet. A successful scan renders actual results;
a failed scan retains the previous results. Other service buttons display
integration messages (Export first opens a Save As dialog). They do not generate
reports or write files.

Sample devices, replies, and reports in `ugnay/demo_data.py` are used only when
`UgnayApp(demo=True)` is requested explicitly, including in presentation tests.
Those fixtures do not describe your actual network.

## File layout and member assignments

| File | Responsibility |
| --- | --- |
| `main.py` | Application entry point |
| `ugnay/app.py` | Member 3: main window, four screens, UI events and result rendering |
| `ugnay/widgets.py` | Shared cards, buttons, tables, notices, icons, and chart |
| `ugnay/models.py` | Shared typed data contracts for all members |
| `ugnay/demo_data.py` | Clearly labeled presentation fixtures |
| `ugnay/discovery.py` | Member 1: Windows network detection, concurrent ICMP probes, and hostname lookup |
| `ugnay/connectivity.py` | Member 2: `test_connection(device, count)` stub |
| `ugnay/reporting.py` | Member 3: report, recommendations, and export stubs |

## Integrate the actual functionality later

Keep service modules independent of Tkinter. Replace each `NotImplementedError`
with the member's implementation and return the corresponding model. All lengthy
service calls already run on a daemon worker thread. Results are passed back
through a queue; Tkinter updates run on the main thread.

### Member 1: discovery

1. `DiscoveryService.detect_network()` now returns the actual Windows `NetworkInfo`.
2. `scan_network(subnet)` returns `DiscoveryResult` with the detected local IP,
   scanned CIDR range, completion timestamp, and a sorted tuple of `Device` records.
3. It uses `hostname=None` if reverse lookup is unavailable; the interface displays
   “Hostname unavailable.” Use `devices=()` for a successful scan with no hosts.
4. It raises an exception for an actual scan failure. The shell displays it and keeps
   the previous view available.

The **Scan Network** button is already connected through `on_scan_network()` to
both service methods. `apply_discovery_result()` renders the returned data.

#### Scan Network workflow

The existing button and tables use this complete path:

```text
Scan Network -> on_scan_network() -> _start_task()
  background worker: detect_network() -> scan_network(network.subnet)
  UI queue: _finish_task() -> apply_discovery_result() -> refresh_views()
  device tables: DeviceTable.set_devices()
```

`_start_task()` starts the progress indicator and disables action buttons before
starting the worker. Further scan requests are ignored while it is busy. The
worker calls only services and `post_to_ui()`, which enqueues a callback without
calling Tkinter. The main thread's queue poll restores controls and renders the
completed result, including network information, timestamp, device counts, and
both device tables. Selection is preserved if the selected IP remains in the
result; otherwise the first returned device is selected, or no device for an
empty result.

Both service errors and a failure to start the worker stop the progress indicator,
restore controls, and show an error on the UI thread while retaining previous
scan results. UI tests use a controlled background scan to verify the thread
boundaries, queue handoff, responsive event loop, and disabled buttons without
performing network operations. This follows
[Tkinter's threading model](https://docs.python.org/3/library/tkinter.html#threading-model).

An address that does not respond is skipped without an error dialog. A missing
hostname keeps the device and displays `Hostname unavailable`. A completed scan
with no responders clears both tables and selection, and displays
`No devices responded to discovery in this range` in the status bar and tables.
Before the first scan, an empty table instead prompts the user to begin scanning.

An unavailable interface raises `NetworkDetectionError` and is displayed as
`Network detection failed`. Invalid subnets, missing probe commands, malformed
probe output, and backend failures raise exceptions and preserve the previous
network, timestamp, devices, and selection. A partially completed scan that
encounters a backend failure does not publish partial results as a successful scan.

#### Local IP and subnet detection

Detection requires Windows PowerShell (`powershell.exe`) and its NetTCPIP module.
It reads `Get-NetIPConfiguration -All`, queries connected interfaces with
`Get-NetIPAddress -AddressFamily IPv4 -PolicyStore ActiveStore`, and parses plain
JSON fields. Python's `ipaddress` computes the subnet from the actual prefix;
for example, `192.168.1.24/26` returns `192.168.1.0/26`.

The selection rule is deterministic:

1. Ignore disconnected adapters, loopback, unspecified/multicast/broadcast
   addresses, IPv6, addresses not in the `Preferred` state, and `SkipAsSource`
   addresses.
2. Prefer physical Ethernet or Wi-Fi over other connected adapters.
3. Within that group, prefer non-link-local addresses, then the lowest IPv4
   interface metric, lowest interface index, and lowest numeric IPv4 address.
4. Link-local IPv4 (`169.254.x.x`) is allowed when no better address is available
   within the selected adapter group. A gateway, DNS server, and internet access
   are not required. No connectivity probe is sent.

To select an intended interface explicitly, use a literal, case-insensitive alias:

```python
from ugnay.discovery import DiscoveryService

network = DiscoveryService(interface_alias="Wi-Fi").detect_network()
print(network.local_ip, network.subnet)
```

Omit `interface_alias` for automatic selection. An explicitly requested interface
must be connected and have a usable IPv4 address; detection does not silently
switch to another interface. The alias is matched in Python, never interpolated
into a PowerShell command. Each call reads fresh adapter data.

Detection raises `NetworkDetectionError` for unsupported platforms, unavailable
PowerShell, command failures (including permission errors), a 20-second command
timeout, malformed output, or no usable interface. The existing UI error handling
can display these errors while retaining previous scan results.

The commands and prefix information follow Microsoft's
[Get-NetIPConfiguration documentation](https://learn.microsoft.com/en-us/powershell/module/nettcpip/get-netipconfiguration)
and [Get-NetIPAddress documentation](https://learn.microsoft.com/en-us/powershell/module/nettcpip/get-netipaddress).

#### Device discovery

`scan_network(subnet)` accepts an IPv4 CIDR string and enumerates `network.hosts()`.
Host bits are normalized to that prefix; no range is silently reduced to `/24`.
Network/broadcast addresses are excluded for ordinary subnets, both `/31`
addresses are included, and `/32` scans its single address. Each candidate,
including the local machine, is included only if it responds to an ICMP echo.

A bounded thread pool runs PowerShell probes using
`System.Net.NetworkInformation.Ping.Send`. Each probe exchanges JSON over stdin
and stdout. Only `IPStatus.Success` (numeric value `0`) from the requested address
counts as a response; ICMP timeouts and unreachable statuses are ordinary misses.
Resource/hardware errors and unknown ICMP statuses fail the scan rather than
being counted as nonresponding devices.
A missing probe command, failed process, process timeout, or malformed output
raises `NetworkScanError` instead of reporting a misleading empty scan.

Responders receive a best-effort `socket.gethostbyaddr()` lookup in a separate
Python process with its own deadline. Lookup failures and timeouts leave
`hostname=None`, keeping the device with the display name `Hostname unavailable`.
Successful lookups use the primary hostname (`socket.gethostbyaddr(ip)[0]`).
Devices have an aware `last_seen` timestamp captured after the response and
`result=None`. The table shows `Not tested` until Member 2's detailed
connectivity test is run.
Records are deduplicated by IP address, then sorted numerically. A successful
scan with no responders returns `devices=()`.

Limits and deadlines are configurable without adding third-party dependencies:

```python
service = DiscoveryService(
    max_workers=16,
    icmp_timeout_ms=1000,
    process_timeout=10.0,  # Seconds, including PowerShell startup overhead.
    hostname_timeout=2.0,  # Seconds for each optional reverse lookup.
    max_hosts=1024,        # Usable candidate addresses, checked before any probes.
)
network = service.detect_network()
result = service.scan_network(network.subnet)
```

The process timeout must exceed the ICMP timeout by at least one second. The
default host limit allows up to 1,024 candidates; an oversized range raises
`ValueError` with its host count and configured limit. This prevents enumerating
an unexpectedly large LAN. PowerShell startup adds overhead to each probe.

The scan reuses the last successful detection on the same service instance. If
called before detection, it detects the local network first. The UI calls
`detect_network()` before every scan, refreshing the adapter context each time.

ICMP discovery finds responders rather than every connected device: devices
that block ICMP or are asleep may be absent. ARP discovery is not implemented.
The API behavior follows
[Python's usable-host enumeration](https://docs.python.org/3/library/ipaddress.html#ipaddress.IPv4Network.hosts)
and [Microsoft's ICMP status documentation](https://learn.microsoft.com/en-us/dotnet/api/system.net.networkinformation.ipstatus).

### Member 2: connectivity and statistics

1. Implement `ConnectivityService.test_connection(device, count)`.
2. Return `PingResult` with one `PingReply` per request and the calculated average,
   maximum, loss percentage, status, and timestamp.
3. Use `latency_ms=None` for a timeout. When all requests time out, return `None`
   for both latency values, `100.0` for packet loss, and `UNREACHABLE` status.
4. Distinguish an unreachable device (a valid result) from failure to execute the
   test (an exception).

Both **Test Connection** and **Run ping test** call `on_test_connection()`;
`apply_ping_result()` updates the shared device table and result displays.
Changing the ping count affects the next request; it does not alter an existing
test's displayed reply count.

### Member 3: reports and recommendations

1. Implement `ReportingService.generate_report(network, devices, generated_at)`
   to return `Report`. Include date/time, detected devices, ping results, and a
   network performance summary in `Report.text`.
2. Implement `get_recommendations(devices)` and call it from `generate_report()`;
   place its results in `Report.recommendations`. The UI displays supplied
   recommendations; it does not inspect firewall or password settings.
3. Implement `export_report(report, destination)` to write UTF-8 text and raise
   exceptions on write failures. The UI opens a Save As dialog and calls the
   method with the selected path. Canceling the dialog does not call the exporter.

The callbacks are `on_generate_report()`, `apply_report()`, and
`on_export_report()`. Report history is held in memory for this UI stage.
The app does not claim to save reports across restarts.

The entry point and the default `UgnayApp()` both start with real-data mode:

```python
from ugnay.app import UgnayApp

UgnayApp(demo=False).mainloop()
```

For the optional sample-data presentation, use `UgnayApp(demo=True).mainloop()`.

You may also inject service objects with the same methods into
`UgnayApp(discovery=..., connectivity=..., reporting=..., demo=False)`.
For a worker you manage yourself, use `app.post_to_ui(callback, result)` to
schedule rendering. Do not call Tkinter widgets from a worker thread.

## Scope

The optional PDF, email, port-scanning, packet-capture, live-monitoring, and cloud
features are omitted. The UI covers the required discovery, connectivity,
statistics, report, and recommendations areas first.

## Verify the interface

The test files described below are absent in the working tree reviewed on
17 November 2026. Restore the maintained suite before running these commands;
the coverage description reflects the earlier 58-test validation. See the
[Module 1 verification section](docs/module-1-network-discovery.md#13-verification-and-recorded-results)
for the recorded results and a live acceptance checklist.

```powershell
python -m unittest discover -s tests -v
```

Discovery checks mock command output, probes, and hostname lookups, covering real
prefixes, adapter selection, offline/link-local networks, bounded concurrency,
`/31` and `/32`, scan-size limits, ICMP statuses, and execution failures. UI checks
inject a fake discovery service, create actual Tkinter windows, and exercise
successful and empty scans, navigation, shared
selection, untested/empty/unreachable states, stub callbacks, export cancellation,
request-count handoff, scan errors, and the smaller-window layout. They do not
perform network operations or write reports.

The startup check verifies an undetected network, zero devices, disabled
device-dependent actions, and the Scan Network prompt. Presentation tests request
`demo=True` and inject a fake discovery service; only the remaining unimplemented
connectivity/reporting actions are expected to show an integration message.

For a live LAN check, run `python main.py --desktop`, use **Scan Network**, and switch
between Overview and Devices while scanning. Confirm both tables show the same
actual devices. Scan again and confirm rows are replaced rather than duplicated.
Live LAN verification is separate from the automated tests above.
