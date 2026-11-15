# UGNAY — LAN Health Checker interface

A runnable Python Tkinter interface based on the supplied Overview, Devices,
Ping tests, and Reports designs. **This is the UI stage only.** Network discovery,
ping execution, statistics calculations, report generation, recommendation
analysis, and text export are intentionally unimplemented service stubs.

## Run

Use Python 3.10 or newer with Tkinter installed:

```powershell
python main.py
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

The initial IP addresses, timestamps, devices, replies, and report are **static
sample data** in `ugnay/demo_data.py`. They do not describe your actual network.
Buttons currently display an integration message identifying the responsible
member (Export first opens a Save As dialog). They do not run network commands,
generate reports, or write files.
The report's example aggregate latency is 5.1 ms across seven successful replies;
example overall loss is 12.5% across eight requests. Untested devices are excluded.

## File layout and member assignments

| File | Responsibility |
| --- | --- |
| `main.py` | Application entry point |
| `ugnay/app.py` | Member 3: main window, four screens, UI events and result rendering |
| `ugnay/widgets.py` | Shared cards, buttons, tables, notices, icons, and chart |
| `ugnay/models.py` | Shared typed data contracts for all members |
| `ugnay/demo_data.py` | Clearly labeled presentation fixtures |
| `ugnay/discovery.py` | Member 1: `detect_network()` and `scan_network(subnet)` stubs |
| `ugnay/connectivity.py` | Member 2: `test_connection(device, count)` stub |
| `ugnay/reporting.py` | Member 3: report, recommendations, and export stubs |

## Integrate the actual functionality later

Keep service modules independent of Tkinter. Replace each `NotImplementedError`
with the member's implementation and return the corresponding model. All lengthy
service calls already run on a daemon worker thread. Results are passed back
through a queue; Tkinter updates run on the main thread.

### Member 1: discovery

1. Implement `DiscoveryService.detect_network()` to return `NetworkInfo`.
2. Implement `scan_network(subnet)` to return `DiscoveryResult` with the actual
   network, scan timestamp, and a tuple of `Device` records.
3. Use `hostname=None` if reverse lookup is unavailable; the interface displays
   “Hostname unavailable.” Use `devices=()` for a successful scan with no hosts.
4. Raise an exception for an actual scan failure. The shell displays it and keeps
   the previous view available.

The **Scan Network** button is already connected through `on_scan_network()` to
both service methods. `apply_discovery_result()` renders the returned data.

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

Start with an empty interface when integrating real services:

```python
from ugnay.app import UgnayApp

UgnayApp(demo=False).mainloop()
```

You may also inject service objects with the same methods into
`UgnayApp(discovery=..., connectivity=..., reporting=..., demo=False)`.
For a worker you manage yourself, use `app.post_to_ui(callback, result)` to
schedule rendering. Do not call Tkinter widgets from a worker thread.

## Scope

The optional PDF, email, port-scanning, packet-capture, live-monitoring, and cloud
features are omitted. The UI covers the required discovery, connectivity,
statistics, report, and recommendations areas first.

## Verify the interface

```powershell
python -m unittest discover -s tests -v
```

These checks create actual Tkinter windows and exercise navigation, shared
selection, untested/empty/unreachable states, stub callbacks, export cancellation,
request-count handoff, scan errors, and the smaller-window layout. They do not
perform network operations or write reports.
