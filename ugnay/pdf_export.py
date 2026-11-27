from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Mapping, Sequence

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfgen import canvas

NAVY = colors.HexColor("#172D48")
BLUE = colors.HexColor("#26649F")
GREY = colors.HexColor("#667C94")
LINE = colors.HexColor("#D8E2EA")
GREEN = colors.HexColor("#27815B")
AMBER = colors.HexColor("#AE6A13")
RED = colors.HexColor("#BF3954")
VIOLET = colors.HexColor("#5048EF")
MAGENTA = colors.HexColor("#E02D9B")
WHITE = colors.white
W, H = A4
MARGIN = 48


def _str(value: Any, fallback: str = "Not available") -> str:
    if value is None or value == "":
        return fallback
    return str(value)


def _dt(value: Any) -> str:
    if value is None or value == "":
        return "Not recorded"

    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )
        except ValueError:
            return value

    if isinstance(value, datetime):
        return value.strftime("%m/%d/%y, %I:%M %p")

    return str(value)


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        import math
        n = float(value)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError):
        return None


def _ms(value: Any) -> str:
    n = _number(value)
    return "Not tested" if n is None else f"{n:.1f} ms"


def _pct(value: Any) -> str:
    n = _number(value)
    return "Not tested" if n is None else f"{n:g}%"


def _fit_text(text: Any, width: float, size: float = 9, font: str = "Helvetica") -> str:
    """Shorten a label instead of drawing into an adjacent table column."""
    txt = _str(text, "-")
    if canvas_string_width(txt, font, size) <= width:
        return txt
    while txt and canvas_string_width(txt + "...", font, size) > width:
        txt = txt[:-1]
    return txt + "..."


def canvas_string_width(value: str, font: str, size: float) -> float:
    from reportlab.pdfbase.pdfmetrics import stringWidth
    return stringWidth(value, font, size)


def _text(c: canvas.Canvas, x: float, y: float, text: Any,
          size: float = 10, color: colors.Color = NAVY,
          bold: bool = False) -> None:
    c.setFillColor(color)
    c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
    c.drawString(x, y, _str(text, "-"))



def _wrapped(c: canvas.Canvas, text: str, x: float, y: float,
             width: float, size: float = 10, leading: float = 15,
             color: colors.Color = NAVY,
             max_lines: int | None = None) -> float:
    """Draw text with automatic line wrapping."""
    lines = simpleSplit(text, "Helvetica", size, width)

    if max_lines is not None:
        lines = lines[:max_lines]

    for line in lines:
        _text(c, x, y, line, size, color)
        y -= leading

    return y


def _footer(c: canvas.Canvas, page_no: int,
            scan: Mapping[str, Any]) -> None:
    """Draw the report footer."""
    c.setStrokeColor(LINE)
    c.line(MARGIN, 39, W - MARGIN, 39)

    _text(
        c, MARGIN, 25,
        "UGNAY | Network Health Checker",
        8, GREY
    )

    c.setFont("Helvetica", 8)
    c.setFillColor(GREY)
    c.drawRightString(
        W - MARGIN, 25,
        f"Scan: {_dt(scan.get('scanned_at'))} | Page {page_no}"
    )


def _device_status(device: Mapping[str, Any]) -> str:
    """Get the latest ping status of a device."""
    ping = device.get("ping")

    if not isinstance(ping, Mapping):
        return "Not tested"

    return _str(ping.get("status"), "Not tested")


def _ping_replies(
    ping: Mapping[str, Any] | None
) -> list[dict[str, Any]]:
    """Extract individual ping replies."""
    if not isinstance(ping, Mapping):
        return []

    records = ping.get("replies") or []
    output = []

    for i, entry in enumerate(records):
        if isinstance(entry, Mapping):
            output.append({
                "sequence": entry.get("sequence", i + 1),
                "latency_ms": _number(entry.get("latency_ms")),
                "tested_at": entry.get(
                    "tested_at", ping.get("tested_at")
                )
            })
        else:
            output.append({
                "sequence": i + 1,
                "latency_ms": _number(entry),
                "tested_at": ping.get("tested_at")
            })

    return output


def _ping_metrics(
    ping: Mapping[str, Any] | None
) -> tuple[int, int, float | None, float | None]:
    """Calculate packet counts, latency, and packet loss."""
    replies = _ping_replies(ping)

    sent = len(replies)
    received = sum(
        reply["latency_ms"] is not None
        for reply in replies
    )

    avg = _number(
        (ping or {}).get("average_latency_ms")
    )
    loss = _number(
        (ping or {}).get("packet_loss_percent")
    )

    if avg is None:
        values = [
            reply["latency_ms"]
            for reply in replies
            if reply["latency_ms"] is not None
        ]
        avg = sum(values) / len(values) if values else None

    if loss is None and sent:
        loss = 100.0 * (sent - received) / sent

    return sent, received, avg, loss


def _chart_title(
    c: canvas.Canvas, x: float, y: float, text: str
) -> None:
    """Draw a consistent chart or section heading."""
    _text(c, x, y, text, 12, NAVY, True)



def _latency_chart(
    c: canvas.Canvas,
    x: float,
    y: float,
    width: float,
    height: float,
    ping: Mapping[str, Any] | None
) -> None:
    """Draw latency values for individual ping requests."""

    _chart_title(c, x, y, "Device Latency Trend")

    replies = _ping_replies(ping)

    left = x + 30
    right = x + width - 10
    bottom = y - height + 28
    top = y - 36

    if not replies:
        _text(c, x + 12, y - 70,
              "No ping data available.", 9, GREY)
        return

    values = [
        reply["latency_ms"]
        for reply in replies
        if reply["latency_ms"] is not None
    ]

    maximum = max(1.0, max(values, default=0) * 1.2)
    plot_height = top - bottom

    # Horizontal grid lines and latency labels
    for fraction in (0, 0.5, 1):
        grid_y = bottom + fraction * plot_height

        c.setStrokeColor(LINE)
        c.setLineWidth(0.5)
        c.line(left, grid_y, right, grid_y)

        _text(
            c, x, grid_y - 3,
            f"{maximum * fraction:.1f}",
            7, GREY
        )

    _text(c, x, y - 23, "Latency (ms)", 7.5, GREY)

    count = len(replies)
    previous = None
    label_step = max(1, (count + 7) // 8)

    for index, reply in enumerate(replies):
        px = (
            (left + right) / 2
            if count == 1
            else left + index * (right - left) / (count - 1)
        )

        latency_value = reply["latency_ms"]

        if index % label_step == 0 or index == count - 1:
            c.setFillColor(GREY)
            c.setFont("Helvetica", 7)
            c.drawCentredString(
                px, bottom - 13,
                str(reply["sequence"])
            )

        if latency_value is None:
            previous = None
            continue

        py = bottom + (
            latency_value / maximum
        ) * plot_height

        if previous is not None:
            c.setStrokeColor(BLUE)
            c.setLineWidth(1.6)
            c.line(previous[0], previous[1], px, py)

        c.setFillColor(BLUE)
        c.circle(px, py, 2.8, stroke=0, fill=1)

        previous = (px, py)


def _response_chart(
    c: canvas.Canvas,
    x: float,
    y: float,
    width: float,
    height: float,
    ping: Mapping[str, Any] | None
) -> None:
    """Draw the successful and unanswered ping counts."""

    _chart_title(c, x, y, "Packet Response Summary")

    sent, received, _, _ = _ping_metrics(ping)
    failed = sent - received

    # Legend above the graph - always visible.
    c.setFillColor(VIOLET)
    c.rect(x + 2, y - 30, 8, 8, stroke=0, fill=1)
    _text(c, x + 15, y - 28, "Replies", 8, GREY)

    c.setFillColor(MAGENTA)
    c.rect(x + width * 0.50, y - 30,
           8, 8, stroke=0, fill=1)
    _text(
        c, x + width * 0.50 + 13,
        y - 28, "No response", 8, GREY
    )

    if sent == 0:
        _text(c, x + 12, y - 75,
              "No ping test available.", 9, GREY)
        return

    left = x + 30
    right = x + width - 10
    bottom = y - height + 28
    top = y - 48

    maximum = max(4, sent)
    plot_height = top - bottom

    # Grid and packet-count labels
    for fraction in (0, 0.5, 1):
        grid_y = bottom + fraction * plot_height

        c.setStrokeColor(LINE)
        c.setLineWidth(0.5)
        c.line(left, grid_y, right, grid_y)

        _text(
            c, x + 5, grid_y - 3,
            f"{maximum * fraction:g}",
            7, GREY
        )

    center = (left + right) / 2
    bar_width = 32

    bars = [
        (center - 43, received, VIOLET),
        (center + 14, failed, MAGENTA)
    ]

    for bar_x, value, color in bars:
        bar_height = (value / maximum) * plot_height

        c.setFillColor(color)
        c.rect(
            bar_x,
            bottom,
            bar_width,
            bar_height,
            stroke=0,
            fill=1
        )

        c.setFillColor(NAVY)
        c.setFont("Helvetica-Bold", 8)
        c.drawCentredString(
            bar_x + bar_width / 2,
            bottom + bar_height + 6,
            str(value)
        )

    c.setFillColor(GREY)
    c.setFont("Helvetica", 8)
    c.drawCentredString(
        center, bottom - 16, "Latest"
    )



def _report_header(
    c: canvas.Canvas,
    scan: Mapping[str, Any],
    logo_path: str | Path | None = None
) -> None:
    """Draw the official UGNAY report header."""

    if logo_path:
        try:
            image = Path(logo_path)
            if image.is_file():
                c.drawImage(
                    ImageReader(str(image)),
                    MARGIN, H - 95,
                    width=42, height=42,
                    preserveAspectRatio=True,
                    anchor="c",
                    mask="auto"
                )
        except (OSError, ValueError):
            pass

    _text(
        c, MARGIN + 53, H - 63,
        "UGNAY", 15, NAVY, True
    )

    _text(
        c, MARGIN + 53, H - 80,
        "Network Health Checker", 9, GREY
    )

    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 15)
    c.drawRightString(
        W - MARGIN, H - 65, "Summary Report"
    )

    _text(
        c, MARGIN, H - 107,
        f"Date: {_dt(scan.get('scanned_at'))}",
        9, GREY
    )



def _page_one(
    c: canvas.Canvas,
    snapshot: Mapping[str, Any],
    logo_path: str | Path | None = None
) -> None:
    """Draw the individual device report on page one."""

    scan = snapshot.get("scan") or {}
    devices = snapshot.get("devices") or []
    selected_ip = snapshot.get("selected_device_ip")

    selected = next(
        (item for item in devices
         if item.get("ip_address") == selected_ip),
        None
    )

    if selected is None and devices:
        selected = devices[0]

    selected = selected or {}

    latest = selected.get("ping")
    history = selected.get("ping_history")

    if history is None:
        history = [latest] if latest else []

    _report_header(c, scan, logo_path)

    # DEVICE INFORMATION
    _text(
        c, MARGIN, 715,
        "Device Information", 12, NAVY, True
    )

    name = _fit_text(
        selected.get("name", "No device selected"),
        350, 12, "Helvetica-Bold"
    )

    _text(c, MARGIN, 693, name, 12, NAVY, True)

    trust = selected.get("trust", "Review")
    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(BLUE)
    c.drawRightString(
        W - MARGIN, 693, _str(trust)
    )

    fields = [
        ("Hostname", selected.get("hostname")),
        ("IP address", selected.get("ip_address")),
        ("Connected subnet", scan.get("subnet")),
        ("First discovered", _dt(
            selected.get("first_discovered")
        )),
        ("Last scan response", _dt(
            selected.get("last_scan_response")
        )),
    ]

    positions = [
        (MARGIN, 670),
        (MARGIN, 649),
        (MARGIN, 628),
        (310, 670),
        (310, 649),
    ]

    for (label, value), (x, y) in zip(fields, positions):
        _text(c, x, y, label, 8, GREY)

        offset = 100 if x == MARGIN else 92
        available = (
            140 if x == MARGIN else W - MARGIN - x - offset
        )

        _text(
            c, x + offset, y,
            _fit_text(value, available, 8.5),
            8.5, NAVY
        )

    # DEVICE CHARTS
    chart_width = (W - 2 * MARGIN - 14) / 2

    _latency_chart(
        c, MARGIN, 592,
        chart_width, 190, latest
    )

    _response_chart(
        c, MARGIN + chart_width + 14, 592,
        chart_width, 190, latest
    )

    # DEVICE CONNECTIVITY SUMMARY
    _text(
        c, MARGIN, 373,
        "Device Connectivity Summary",
        12, NAVY, True
    )

    sent = sum(
        len(test.get("replies") or [])
        for test in history
    )

    count = selected.get(
        "ping_tests_conducted", len(history)
    )

    _text(
        c, MARGIN, 352,
        f"Packets sent: {sent}", 9, NAVY
    )

    _text(
        c, MARGIN, 334,
        f"Ping tests conducted: {count}", 9, NAVY
    )

    latest_text = (
        f"{_ms(latest.get('average_latency_ms'))} / "
        f"{_pct(latest.get('packet_loss_percent'))} loss"
        if latest else "No test yet"
    )

    _text(
        c, MARGIN, 316,
        f"Latest test: {latest_text}", 9, NAVY
    )

    # DEVICE CONNECTIVITY TEST LOGS
    _text(
        c, MARGIN, 285,
        "Device Connectivity Test Logs",
        12, NAVY, True
    )

    columns = [
        (MARGIN, "Packet"),
        (117, "Success"),
        (191, "Failure"),
        (266, "Error"),
        (338, "Test Time"),
    ]

    for x, heading in columns:
        _text(
            c, x, 265,
            heading, 8, GREY, True
        )

    c.setStrokeColor(LINE)
    c.line(MARGIN, 257, W - MARGIN, 257)

    rows = []

    for test in history:
        for reply in _ping_replies(test):
            rows.append((
                reply,
                test.get("tested_at")
            ))

    if not rows:
        _text(
            c, MARGIN, 239,
            "No ping test logs available.",
            9, GREY
        )
    else:
        # Limit rows to keep the report on one page.
        for index, (reply, tested_at) in enumerate(
            rows[:10]
        ):
            y = 241 - index * 14
            success = reply["latency_ms"] is not None

            values = [
                reply["sequence"],
                "1" if success else "0",
                "0" if success else "1",
                "-",
                _dt(tested_at),
            ]

            for (x, _), value in zip(columns, values):
                _text(
                    c, x, y,
                    value, 8, NAVY
                )

        if len(rows) > 10:
            _text(
                c, MARGIN, 83,
                f"Showing 10 of {len(rows)} saved packet records.",
                8, GREY
            )

    _footer(c, 1, scan)



def _page_two(
    c: canvas.Canvas,
    snapshot: Mapping[str, Any],
    logo_path: str | Path | None = None
) -> None:
    """Draw the overall network assessment on page two."""

    scan = snapshot.get("scan") or {}
    devices = snapshot.get("devices") or []

    # Use one latest saved ping test per device.
    measured = [
        (device, device["ping"])
        for device in devices
        if isinstance(device.get("ping"), Mapping)
    ]

    tested = len(measured)
    total = len(devices)
    untested = total - tested

    latencies = [
        value
        for _, ping in measured
        if (value := _number(
            ping.get("average_latency_ms")
        )) is not None
    ]

    losses = [
        value
        for _, ping in measured
        if (value := _number(
            ping.get("packet_loss_percent")
        )) is not None
    ]

    avg_latency = (
        sum(latencies) / len(latencies)
        if latencies else None
    )

    avg_loss = (
        sum(losses) / len(losses)
        if losses else None
    )

    # Match the health assessment in reports.js.
    urgent = any(
        ping.get("status") == "Unreachable"
        or (
            (loss := _number(
                ping.get("packet_loss_percent")
            )) is not None and loss >= 10
        )
        or (
            (lat := _number(
                ping.get("average_latency_ms")
            )) is not None and lat >= 100
        )
        for _, ping in measured
    )

    fair = any(
        ping.get("status") == "Packet loss"
        or (
            (loss := _number(
                ping.get("packet_loss_percent")
            )) is not None and loss > 0
        )
        or (
            (lat := _number(
                ping.get("average_latency_ms")
            )) is not None and lat >= 50
        )
        for _, ping in measured
    )

    if total == 0:
        health = "No devices detected"
    elif tested == 0:
        health = "Not tested"
    elif urgent:
        health = "Needs attention"
    elif fair:
        health = "Fair"
    elif untested:
        health = "Partially tested"
    else:
        health = "Healthy"

    # REPORT HEADER
    _report_header(c, scan, logo_path)

    # OVERALL NETWORK ASSESSMENT
    _text(
        c, MARGIN, 710,
        "Overall Network Assessment",
        13, NAVY, True
    )

    _text(
        c, MARGIN, 688,
        f"Selected scan: {_dt(scan.get('scanned_at'))}",
        9, GREY
    )

    status_color = (
        RED if health == "Needs attention"
        else AMBER if health in (
            "Fair", "Partially tested", "Not tested"
        )
        else GREEN if health == "Healthy"
        else GREY
    )

    _text(c, MARGIN, 660, "Overall status:", 10, GREY)
    _text(c, 143, 660, health, 10, status_color, True)

    # Network summary metrics
    _text(c, MARGIN, 633, "Devices tested", 8, GREY)
    _text(c, MARGIN, 615, f"{tested} / {total}",
          12, NAVY, True)

    _text(c, 220, 633, "Average latency", 8, GREY)
    _text(c, 220, 615, _ms(avg_latency),
          12, NAVY, True)

    _text(c, 392, 633, "Average packet loss", 8, GREY)
    _text(c, 392, 615, _pct(avg_loss),
          12, NAVY, True)

    # DISCOVERED DEVICES
    _text(
        c, MARGIN, 580,
        "Discovered Devices",
        12, NAVY, True
    )

    columns = [
        (MARGIN, "Device Name"),
        (207, "IP Address"),
        (316, "Trust"),
        (393, "Ping Status"),
    ]

    for x, heading in columns:
        _text(c, x, 556, heading, 8, GREY, True)

    c.setStrokeColor(LINE)
    c.setLineWidth(0.6)
    c.line(MARGIN, 549, W - MARGIN, 549)

    if not devices:
        _text(
            c, MARGIN, 529,
            "No devices discovered in this scan.",
            9, GREY
        )
    else:
        for index, device in enumerate(devices[:10]):
            y = 530 - index * 17

            values = [
                _fit_text(
                    device.get("name"), 150, 8
                ),
                _str(device.get("ip_address"), "-"),
                _str(device.get("trust"), "Review"),
                _device_status(device),
            ]

            for (x, _), value in zip(columns, values):
                _text(c, x, y, value, 8, NAVY)

        if len(devices) > 10:
            _text(
                c, MARGIN, 351,
                f"Showing 10 of {len(devices)} discovered devices.",
                8, GREY
            )

    # CONNECTIVITY FINDINGS
    _text(
        c, MARGIN, 334,
        "Connectivity Findings",
        12, NAVY, True
    )

    unreachable = sum(
        ping.get("status") == "Unreachable"
        for _, ping in measured
    )

    high_loss = sum(
        (value := _number(
            ping.get("packet_loss_percent")
        )) is not None and value >= 10
        for _, ping in measured
    )

    some_loss = sum(
        (value := _number(
            ping.get("packet_loss_percent")
        )) is not None and 0 < value < 10
        for _, ping in measured
    )

    high_latency = sum(
        (value := _number(
            ping.get("average_latency_ms")
        )) is not None and value >= 100
        for _, ping in measured
    )

    elevated_latency = sum(
        (value := _number(
            ping.get("average_latency_ms")
        )) is not None and 50 <= value < 100
        for _, ping in measured
    )

    findings = []

    if unreachable:
        findings.append(
            f"{unreachable} device(s) returned no ping responses. "
            "Check connectivity and ICMP settings."
        )

    if high_loss or some_loss:
        findings.append(
            f"{high_loss} device(s) had high packet loss; "
            f"{some_loss} had some packet loss."
        )

    if high_latency or elevated_latency:
        findings.append(
            f"{high_latency} device(s) had high latency; "
            f"{elevated_latency} had elevated latency."
        )

    if untested:
        findings.append(
            f"{untested} of {total} discovered devices "
            "have no saved ping test for this scan."
        )

    if not findings:
        findings.append(
            "No connectivity issues detected in the "
            "available latest ping results."
            if measured else
            "No ping test results are available for this scan."
        )

    y = 313

    for finding in findings:
        y = _wrapped(
            c, "- " + finding,
            MARGIN + 4, y,
            W - 2 * MARGIN - 8,
            size=8.5,
            leading=12,
            color=NAVY,
            max_lines=2
        )
        y -= 6

    # GENERAL SECURITY RECOMMENDATIONS
    _text(
        c, MARGIN, 197,
        "General Security Recommendations",
        12, NAVY, True
    )

    recommendations = [
        "Use strong Wi-Fi and router administrator passwords.",
        "Keep router firmware updated.",
        "Enable appropriate firewall protection.",
    ]

    y = 176

    for recommendation in recommendations:
        _text(
            c, MARGIN + 4, y,
            "- " + recommendation,
            8.5, NAVY
        )
        y -= 21

    # REPORT NOTE
    _wrapped(
        c,
        "Network averages cover tested devices only. "
        "Security recommendations are general precautions, "
        "not detected vulnerabilities.",
        MARGIN, 90,
        W - 2 * MARGIN,
        size=8,
        leading=11,
        color=GREY
    )

    _footer(c, 2, scan)



def generate_pdf(
    snapshot: Mapping[str, Any],
    logo_path: str | Path | None = None
) -> bytes:
    """Generate the complete two-page UGNAY PDF report."""

    buffer = BytesIO()

    c = canvas.Canvas(
        buffer,
        pagesize=A4,
        pageCompression=1
    )

    c.setTitle("UGNAY Network Health Report")
    c.setAuthor("UGNAY Network Health Checker")
    c.setSubject("Network connectivity assessment")

    # Page 1: Individual Device Report
    _page_one(c, snapshot, logo_path)
    c.showPage()

    # Page 2: Overall Network Assessment
    _page_two(c, snapshot, logo_path)
    c.showPage()

    c.save()

    return buffer.getvalue()


