# UGNAY System Progress Report

**Modules 1 and 2 — implementation status and sample code**

Report date: **17 November 2026**  
Reviewed source snapshot: **`6b9bf94`**, including the current working tree.

This report describes observed implementation progress, current focused checks,
earlier live verification, and remaining work. Source code takes precedence over
older README statements. Completion percentages and delivery dates are not
estimated because no weighted project baseline or schedule was supplied.

## Contents

1. [Overall progress](#1-overall-progress)
2. [System structure and handoff](#2-system-structure-and-handoff)
3. [Module 1: Network Discovery](#3-module-1-network-discovery)
4. [Module 2: Connectivity and Statistics](#4-module-2-connectivity-and-statistics)
5. [User-interface integration](#5-user-interface-integration)
6. [Verification evidence](#6-verification-evidence)
7. [Remaining work and limitations](#7-remaining-work-and-limitations)
8. [Next acceptance checks](#8-next-acceptance-checks)
9. [Source provenance](#9-source-provenance)

## 1. Overall progress

UGNAY currently implements the core Windows LAN discovery and per-device
connectivity workflow. The application starts without sample data, discovers
responding IPv4 devices, and can run selected-device ping tests with calculated
latency, packet loss, status labels, reply output, and a chart.

The full system is still in development. Module 3's reporting, recommendations,
and in-app export services remain unimplemented. The maintained regression-test
files are absent, and Module 2 needs additional robustness work before broad
environmental acceptance.

| Area | Current status | Evidence and practical limit |
| --- | --- | --- |
| Module 1: network discovery | Implemented; prior live LAN check recorded | Real IPv4/subnet detection, concurrent ICMP probes, optional names, and UI publication. Current focused checks also passed. |
| Module 2: connectivity/statistics | Implemented; focused mocked checks passed | Actual ping execution and statistics code are present. The current report did not perform a live Module 2 network test. |
| Shared UI and data models | Implemented for core flows | Startup, navigation, shared selection, worker/UI queue, metrics, tables, reply output, chart, and notifications. |
| Module 3: reports/recommendations/export | UI exists; service implementation pending | Three methods in `ugnay/reporting.py` raise `NotImplementedError`. |
| Automated regression suite | Restoration required | `tests/test_discovery.py` and `tests/test_ui.py` are absent in the reviewed working tree. |
| Project documentation | Available; status refresh needed | Earlier documentation still labels Module 2 as a stub. This report reflects the newer source. |

This PDF is project documentation generated outside the application. It does not
indicate that UGNAY's in-app report-generation or export service is implemented.

## 2. System structure and handoff

| File | Role in the current system |
| --- | --- |
| `main.py` | Launches `UgnayApp(demo=False)`. |
| `ugnay/discovery.py` | Module 1 detection, probing, name lookup, and device snapshots. |
| `ugnay/connectivity.py` | Module 2 ping requests, reply parsing, statistics, and status classification. |
| `ugnay/models.py` | Frozen shared models, including `Device`, `DiscoveryResult`, `PingReply`, and `PingResult`. |
| `ugnay/app.py` | UI events, worker dispatch, queue handling, shared state, result rendering, and notifications. |
| `ugnay/widgets.py` | Tables, badges, notices, and the reply-latency chart. |
| `ugnay/reporting.py` | Pending Module 3 service methods. |

The implemented feature path is:

```text
Real-data startup
  -> Scan Network
  -> Module 1: detect network and discover responders
  -> DiscoveryResult -> shared Device table
  -> Select device and choose 4, 10, or 20 requests
  -> Module 2: execute pings and calculate statistics
  -> PingResult -> tables, details, reply output, chart, notification
  -> Module 3 report/recommendations/export: pending
```

Networking runs through background service work. Results return through the UI
queue; the Tkinter thread updates widgets. Busy state disables action buttons
during an operation. Code samples below are selected source excerpts with
normalized indentation, not complete standalone programs. Their variables and
imports come from the enclosing modules and methods.

## 3. Module 1: Network Discovery

### 3.1 Implemented features

| Feature | Current behavior |
| --- | --- |
| Local address and subnet | Reads Windows adapter/address data as JSON; uses the actual prefix instead of assuming `/24`. |
| Interface choice | Supports an explicit alias; otherwise prioritizes physical Ethernet/Wi-Fi, then address/metric/index tie breakers. |
| Candidate validation | IPv4 only; normalizes the requested prefix and enforces a configurable host limit. |
| Host enumeration | Uses `network.hosts()`, including the special `/31` and `/32` cases. |
| Concurrent probing | Defaults to 16 workers, 1,000 ms ICMP timeout, and a 10-second probe-process deadline. |
| Optional hostname | Reverse lookup after a response; separate 2-second resolver-process deadline. |
| Result construction | Unique IP records, numeric sorting, aware observation/completion timestamps, and `result=None`. |
| Error semantics | Ordinary missed responses are skipped; backend failures raise and preserve the prior UI snapshot. |
| Empty result | Clears selection/tables and displays `No devices responded to discovery in this range`. |

The default host limit is 1,024 usable candidates. Device classification, MAC
discovery, ARP assistance, IPv6, and continuous monitoring are outside this
implementation. A device that blocks ICMP can be absent from discovery.

### 3.2 Actual subnet calculation and interface ranking

After validating the Windows JSON fields, this block calculates the CIDR and ranks an eligible adapter. Physical Ethernet/Wi-Fi share the first preference level.

Source: `ugnay/discovery.py`, lines 211–214.

```python
interface = IPv4Interface(f"{address}/{prefix}")
physical_lan = hardware and interface_type in (6, 71)
priority = (not physical_lan, address.is_link_local, metric, index, int(address))
candidates.append((priority, NetworkInfo(str(address), str(interface.network))))
```

### 3.3 Concurrent discovery and failure propagation

The pool limits active work. Device records are keyed by address. A worker failure cancels queued work and propagates instead of becoming a successful empty scan.

Source: `ugnay/discovery.py`, lines 255–267.

```python
with ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="ugnay-discovery") as executor:
    futures = [executor.submit(self._discover_device, str(address)) for address in network.hosts()]
    try:
        for future in as_completed(futures):
            device = future.result()
            if device is not None:
                devices_by_ip[device.ip_address] = device
    except Exception:
        # Cancel queued probes; running subprocesses still have deadlines.
        for future in futures:
            future.cancel()
        raise
```

### 3.4 Responding device records and optional names

Only a responding address becomes a Device. The optional lookup can return None; the shared model then displays Hostname unavailable. Module 2 measurements remain unset until a connection test is run.

Source: `ugnay/discovery.py`, lines 275–286.

```python
def _discover_device(self, ip_address: str) -> Device | None:
    """Build an untested device record only after observing an ICMP response."""
    if not self._probe_host(ip_address):
        return None
    last_seen = datetime.now().astimezone()
    hostname = self._resolve_hostname(ip_address)
    return Device(
        ip_address=ip_address,
        hostname=hostname,
        last_seen=last_seen,
        result=None,
    )
```

## 4. Module 2: Connectivity and Statistics

### 4.1 Implemented features

| Feature | Current behavior |
| --- | --- |
| Request count | Supports 4, 10, or 20 requests through `ALLOWED_COUNTS` and the UI dropdown. |
| Address validation | Parses the selected address and rejects invalid addresses and IPv6. |
| Ping execution | Executes one Windows `ping` request per sequence using `-4 -n 1 -w 1000`. |
| Execution deadline | Applies a five-second subprocess deadline to each request. |
| Reply parsing | Reads English `Reply from ... time=...ms` or `time<...ms` lines; skips unreachable messages. |
| Request history | Returns one `PingReply` per request; `latency_ms=None` represents a missed request. |
| Statistics | Average and maximum use successful replies; packet loss uses all requested attempts. |
| Classification | `Responding`, `Packet loss`, or `Unreachable`. |
| Missing utility / OS error | Raises a descriptive `RuntimeError`. |
| UI handoff | Returns `PingResult` for the shared table, metrics, chart, output, and notifications. |

The current implementation counts subprocess timeouts and nonzero command exits
as missed requests. This is different from Module 1's stricter distinction
between ICMP nonresponse and probe-process failures.

### 4.2 Windows ping execution

This call is inside the request-sequence loop. Output is captured for parsing, the timeout is separate from the ICMP wait, and Windows helper windows are hidden.

Source: `ugnay/connectivity.py`, lines 75–91.

```python
completed = subprocess.run(
    [
        "ping",
        "-4",
        "-n", "1",
        "-w", str(self.TIMEOUT_MS),
        str(ip),
    ],
    capture_output=True,
    text=True,
    errors="replace",
    timeout=5,
    creationflags=getattr(
        subprocess, "CREATE_NO_WINDOW", 0
    ),
)
```

### 4.3 Extracting latency from reply output

The parser handles the current English Windows reply format. Values reported as time<1ms are represented as an approximate 0.5ms; this is not an exact sub-millisecond measurement.

Source: `ugnay/connectivity.py`, lines 19–51.

```python
def _parse_latency(output: str):
    """Extract latency from a successful Windows ping reply."""

    # Only accept an actual reply from the target, not an error.
    reply_pattern = re.compile(
        r"Reply from\s+([0-9.]+):[^\r\n]*",
        re.IGNORECASE,
    )

    for match in reply_pattern.finditer(output):
        line = match.group(0)

        # Ignore "Destination host unreachable" responses.
        if "unreachable" in line.lower():
            continue

        # Windows may report time<1ms or time=3ms.
        latency_match = re.search(
            r"time\s*([=<])\s*(\d+(?:\.\d+)?)\s*ms",
            line,
            re.IGNORECASE,
        )

        if latency_match:
            value = float(latency_match.group(2))

            # Approximate Windows time<1ms as 0.5ms.
            if latency_match.group(1) == "<":
                return value / 2

            return value

    return None
```

### 4.4 Calculating latency and packet loss

Lost requests are excluded from latency averages and maxima but remain in the loss denominator. With no successful replies, latency statistics are None rather than zero.

Source: `ugnay/connectivity.py`, lines 124–143.

```python
successful_latencies = [
    reply.latency_ms
    for reply in replies
    if reply.latency_ms is not None
]

successful_count = len(successful_latencies)
lost_count = count - successful_count

packet_loss = (lost_count / count) * 100

if successful_count > 0:
    average_latency = (
        sum(successful_latencies) / successful_count
    )
    maximum_latency = max(successful_latencies)
else:
    average_latency = None
    maximum_latency = None
```

### 4.5 Status classification and result packaging

The result is independent of Tkinter. It includes the target, test time, ordered replies, statistics, and an explicit status.

Source: `ugnay/connectivity.py`, lines 144–159.

```python
if successful_count == 0:
    status = DeviceStatus.UNREACHABLE
elif lost_count > 0:
    status = DeviceStatus.PACKET_LOSS
else:
    status = DeviceStatus.RESPONDING

return PingResult(
    ip_address=str(ip),
    tested_at=tested_at,
    replies=tuple(replies),
    average_latency_ms=average_latency,
    maximum_latency_ms=maximum_latency,
    packet_loss_percent=packet_loss,
    status=status,
)
```

### 4.6 Statistics examples used for verification

These values are mocked verification inputs, not measurements from the user's LAN.

| Latencies in milliseconds | Average | Maximum | Loss | Expected status |
| --- | ---: | ---: | ---: | --- |
| `2, 4, 6, 8` | 5 ms | 8 ms | 0% | Responding |
| `2, timeout, 4, timeout` | 3 ms | 4 ms | 50% | Packet loss |
| Four timeouts | None | None | 100% | Unreachable |

The formulas are `loss = lost_count / requested_count * 100`,
`average = sum(successful_latencies) / successful_count`, and
`maximum = max(successful_latencies)`, with the no-success case handled separately.

## 5. User-interface integration

The application connects both services to the same background-task/queue
mechanism. A scan publishes a fresh device snapshot. A selected-device test
attaches its PingResult to that device and refreshes the shared screens.

| UI area | Current integration |
| --- | --- |
| Overview and Devices | Shared records, selected device, latest test status, and packet-loss values where shown. |
| Ping tests | Selected target, 4/10/20 request count, average/max latency, loss, individual replies, and chart. |
| Notifications | Information for full response; warnings for partial loss or no response. |
| Last seen | Updated to the test time when at least one reply is parsed; retained on no response. |
| Busy/empty/error states | Progress and disabled actions while working; empty results and failures remain distinct. |

`Device.result=None` means no connectivity measurement is attached yet.
`PingReply.latency_ms=None` means that particular request has no parsed successful
latency. `PingResult` carries all aggregate measurements and the resulting status.

### 5.1 Scan button handoff

The UI event delegates both network operations to the service worker. The success callback publishes the completed snapshot on the UI thread.

Source: `ugnay/app.py`, lines 662–667.

```python
def on_scan_network(self):
    """Run both discovery service calls on the existing background worker."""
    def work():
        network = self.discovery.detect_network()
        return self.discovery.scan_network(network.subnet)
    self._start_task("Scanning network", work, self.apply_discovery_result)
```

### 5.2 Attaching Module 2 results and updating last seen

This is the first update block inside apply_ping_result(). The current method also performs a second replacement/refresh later; removing that duplication is listed as remaining cleanup.

Source: `ugnay/app.py`, lines 721–740.

```python
# Check if the device responded.
successful = any(
    reply.latency_ms is not None
    for reply in result.replies
)

# Update the connectivity result and Last seen.
self.devices[result.ip_address] = replace(
    self.devices[result.ip_address],
    result=result,
    last_seen=(
        result.tested_at
        if successful
        else self.devices[result.ip_address].last_seen
    ),
)

self.last_ping_time = result.tested_at
self.refresh_views()
```

## 6. Verification evidence

### 6.1 Current focused checks

For this report, **15 of 15 focused checks passed**.
All network operations were mocked. Seven source files were also parsed for
Python syntax. The UI check used the current ConnectivityService with mocked
ping output and an actual Tkinter instance; it verified both table statuses,
metric values, chart data, and a success notification.

| Group | Checks | Observed result |
| --- | ---: | --- |
| Source syntax | 1 | Seven Python files parsed. |
| Module 1 service behavior | 4 | Prefixes, sorted responders/missing names, empty results, and backend error propagation passed. |
| Module 2 service behavior | 9 | Reply outcomes, 10/20 counts, timeout handling, argument validation, missing command, and parser behavior passed. |
| Current Module 2 UI handoff | 1 | Statistics, chart, notification, and both table statuses updated. |

Evidence is stored locally in `output/progress_report_validation.json` with its
helper `output/progress_report_checks.py`. These files are local working artifacts
under the Git-ignored output directory, not a restored maintained test suite.

### 6.2 Earlier live Module 1 evidence

The existing `output/live_discovery_results.json` records two earlier completed
LAN scans through the real discovery/UI workflow. Both found nine responding
devices and populated both tables without duplicate rows.

| Scan | Duration | Devices | Overview / Devices rows | Largest UI heartbeat gap |
| --- | ---: | ---: | --- | ---: |
| 1 | 43.275 s | 9 | 9 / 9 | 0.158 s |
| 2 | 42.832 s | 9 | 9 / 9 | 0.204 s |

This was an instrumented hidden-window Tkinter check with real LAN discovery,
not a fresh live scan for this report. The artifact contains no scan timestamp;
no date or current network inventory is inferred from it. It provides no live
Module 2 measurement evidence.

### 6.3 Regression coverage status

An earlier version passed 58 automated checks. The maintained test files are now
absent, and the code has since gained the current Module 2 implementation and UI
changes. That earlier count must not be presented as a current full-system pass.
The 15 focused checks above establish useful current evidence but do not replace
the full regression suite or live Module 2 acceptance testing.

## 7. Remaining work and limitations

| Area | Current finding | Remaining work |
| --- | --- | --- |
| Module 3 | Report generation, recommendations, and text export raise NotImplementedError. | Implement the three ReportingService methods and connect meaningful report content to the existing screen. |
| Maintained tests | Current test files are absent. | Restore tests matching the current services/UI and extend Module 2 regression coverage. |
| Module 2 localization | Parser requires English Reply from/time text. A mocked non-English response produced no latency. | Support the intended Windows locales or use structured response data. |
| Module 2 reply identity | Parser captures a reply IP but does not compare it with the requested target. A foreign-address example returned 2.0ms. | Validate reply identity before accepting a measurement. |
| Failure classification | A five-second ping process timeout currently becomes a lost packet; nonzero exits are also missed requests. | Define and test the desired distinction between execution failures and valid nonresponses. |
| Timestamp consistency | Module 1 uses timezone-aware times; Module 2 uses naive datetime.now(). | Standardize timestamp conventions before cross-module history/report calculations. |
| UI result processing | One completed ping result triggers refresh_views() twice in the current callback. | Consolidate the duplicate replacement/refresh while retaining last-seen and notification behavior. |
| Documentation | README and earlier Module 1 documentation still describe connectivity/statistics as stubs. | Refresh status statements to match the merged Module 2 implementation. |
| Discovery coverage | ICMP-only, IPv4, one selected network context, bounded host count. | Keep the supported scope explicit; evaluate additional discovery methods if required. |
| Scan lifecycle | No user-facing cancellation or whole-scan deadline. | Add cancellation and lifecycle checks if the project requires them. |

These items describe the reviewed source and observed behavior. The reporting
task did not modify the application to address them. Module 2's current happy-path
and statistics checks passed despite the robustness gaps listed above.

## 8. Next acceptance checks

1. Restore the maintained regression files, with networking mocked in automated
   tests. Run `python -m unittest discover -s tests -v` and confirm a meaningful
   nonzero test count. Empty test discovery is not evidence of correctness.
2. On Windows, run `python main.py` and confirm undetected network/zero devices
   before scanning. Compare the detected interface and prefix with Windows.
3. Scan twice and verify responsive navigation, consistent tables, updated
   timestamps, and no duplicate rows.
4. Select a known responding device and run 4, 10, and 20 requests. Compare reply
   counts, average/max latency, packet loss, status, chart, and notification.
5. Use deterministic mocked cases for partial/no response, localized output,
   foreign-address replies, missing ping utility, and process failures.
6. Complete Module 3 and verify that its report uses actual Module 1/2 model data,
   including missing measurements and timezone-consistent timestamps.

The next integration milestone is reliable discovery-to-connectivity behavior
with maintained regression coverage, followed by functional reporting/export.
No completion date is assigned in this report.

## 9. Source provenance

The following source fingerprints identify the reviewed files. Code-sample line
references apply to this snapshot and may shift after later edits.

| File | SHA-256 prefix | Lines |
| --- | --- | ---: |
| `main.py` | `7412e9f4aadecb75` | 5 |
| `ugnay/discovery.py` | `9121eb59cdfdf8bf` | 347 |
| `ugnay/connectivity.py` | `7df4d01d5376fa27` | 159 |
| `ugnay/models.py` | `2a23ef7da5f24fc5` | 79 |
| `ugnay/app.py` | `3d0a18c2309777f1` | 924 |
| `ugnay/widgets.py` | `88ea5c0d74985a05` | 273 |
| `ugnay/reporting.py` | `6391ea523786efd1` | 22 |

Implementation references are the files listed above. Supporting local evidence
is `output/progress_report_validation.json` and the prior
`output/live_discovery_results.json`. Output artifacts are not guaranteed to be
available in another checkout. The report and PDF can be regenerated from the
editable Markdown source when progress changes.
