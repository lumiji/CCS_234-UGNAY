"""Fixed presentation fixtures, NOT discovered hosts or computed test results.

All timestamps and statistics below are sample content. This module performs
no networking, latency calculations, recommendation analysis, or report export.
"""

from datetime import datetime, timedelta, timezone

from .models import (
    Device, DeviceStatus, NetworkInfo, PingReply, PingResult, Recommendation, Report,
)

SAMPLE_TIME = datetime(2026, 11, 15, 9, 41, tzinfo=timezone(timedelta(hours=8)))
SAMPLE_NETWORK = NetworkInfo("192.168.1.10", "192.168.1.0/24")

SAMPLE_DEVICES = (
    Device(
        "192.168.1.1", "Router", "router", SAMPLE_TIME,
        PingResult(
            "192.168.1.1", SAMPLE_TIME,
            (PingReply(1, 3.0), PingReply(2, 3.0), PingReply(3, 3.0), PingReply(4, 3.0)),
            3.0, 3.0, 0.0, DeviceStatus.RESPONDING,
        ),
    ),
    Device(
        "192.168.1.24", "Office laptop", "computer", SAMPLE_TIME,
        PingResult(
            "192.168.1.24", SAMPLE_TIME,
            (PingReply(1, 5.6), PingReply(2, 7.2), PingReply(3, 11.2), PingReply(4, None)),
            8.0, 11.2, 25.0, DeviceStatus.PACKET_LOSS,
        ),
    ),
    Device("192.168.1.35", None, "unknown", SAMPLE_TIME),
)

SAMPLE_RECOMMENDATIONS = (
    Recommendation(
        "Packet loss on Office laptop",
        "One sample request timed out. Repeat the test after real connectivity testing is connected.",
        "warning",
    ),
    Recommendation(
        "Keep your firewall enabled",
        "Allow only trusted applications and keep your operating system up to date.",
    ),
    Recommendation(
        "Use strong, unique passwords",
        "Change default router credentials and use a strong Wi-Fi password.",
    ),
)

# Intentionally written out; this is a preview fixture, not a report generator.
SAMPLE_REPORT_TEXT = """UGNAY
LAN HEALTH CHECKER REPORT — SAMPLE PREVIEW
Generated: 15 Nov 2026, 9:41 AM (UTC+08:00)

NETWORK SUMMARY
Local IP address : 192.168.1.10
Network range    : 192.168.1.0/24
Devices detected : 3
Devices tested   : 2
Average latency  : 5.1 ms (7 successful replies)
Maximum latency  : 11.2 ms
Packet loss      : 12.5% (1 of 8 requests)
Network status   : Attention needed

DETECTED DEVICES
Router              192.168.1.1    Responding
  Average: 3.0 ms | Maximum: 3.0 ms | Loss: 0%
  Replies: 3.0 ms, 3.0 ms, 3.0 ms, 3.0 ms
Office laptop       192.168.1.24   Packet loss
  Average: 8.0 ms | Maximum: 11.2 ms | Loss: 25%
  Replies: 5.6 ms, 7.2 ms, 11.2 ms, Timed out
Hostname unavailable 192.168.1.35  Not tested
  Average: — | Maximum: — | Loss: —

PERFORMANCE SUMMARY
One of the two tested devices has packet loss.
The third device has not been tested.

SECURITY RECOMMENDATIONS
• Re-test Office laptop to check for recurring packet loss.
• Keep your firewall enabled and your software updated.
• Use strong, unique Wi-Fi and router administrator passwords.

Sample data only. No network scan or ping test has been run.
"""

SAMPLE_REPORTS = (
    Report("sample-current", SAMPLE_TIME, 3, 5.1, 12.5, "Attention needed",
           SAMPLE_REPORT_TEXT, SAMPLE_RECOMMENDATIONS),
)

# Fixed chart values belonging to the sample laptop test, not live monitoring.
SAMPLE_ACTIVITY = (("Reply 1", 5.6), ("Reply 2", 7.2), ("Reply 3", 11.2), ("Reply 4", None))
