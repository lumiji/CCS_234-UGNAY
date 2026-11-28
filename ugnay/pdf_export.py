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
    tests: Sequence[Mapping[str, Any]] | None
) -> None:
    """Plot packet latency for the latest three tests in this scan."""

    tests = list(tests or [])[:3]

    if not tests:
        _text(c, x + 12, y - 70,
              "No ping data available.", 9, GREY)
        return

    series = [_ping_replies(test) for test in tests]

    values = [
        reply["latency_ms"]
        for replies in series
        for reply in replies
        if reply["latency_ms"] is not None
    ]

    count = max(1, *(len(replies) for replies in series))
    maximum = max(1.0, max(values, default=0) * 1.2)

    left, right = x + 31, x + width - 10
    bottom, top = y - height + 39, y - 35

    _text(c, x, y - 22, "Latency (ms)", 7.5, GREY)

    # Grid and Y-axis labels
    for fraction in (0, 0.5, 1):
        grid_y = bottom + fraction * (top - bottom)

        c.setStrokeColor(LINE)
        c.setLineWidth(0.5)
        c.line(left, grid_y, right, grid_y)

        _text(
            c, x, grid_y - 3,
            f"{maximum * fraction:.1f}", 7, GREY
        )

    # Packet sequence labels
    label_step = max(1, (count + 5) // 6)

    for packet in range(1, count + 1):
        if (
            packet == 1
            or packet == count
            or (packet - 1) % label_step == 0
        ):
            px = left + (
                (packet - 1) / max(1, count - 1)
            ) * (right - left)

            c.setFillColor(GREY)
            c.setFont("Helvetica", 6.5)
            c.drawCentredString(
                px, bottom - 13, str(packet)
            )

    # Draw one line for each saved test
    labels = ("Latest", "Previous 1", "Previous 2")
    palette = (
    BLUE,                         # Latest
    colors.HexColor("#C3427A"),  # Previous 1
    colors.HexColor("#578A3F"),  # Previous 2
    )

    for i, replies in enumerate(series):
        previous = None
        previous_seq = None

        for j, reply in enumerate(replies):
            value = reply["latency_ms"]
            sequence = _number(reply.get("sequence"))
            sequence = (
                int(sequence)
                if sequence is not None else j + 1
            )

            if value is None:
                previous = None
                previous_seq = None
                continue

            px = left + (
                (sequence - 1) / max(1, count - 1)
            ) * (right - left)

            py = bottom + (
                value / maximum
            ) * (top - bottom)


            
            if (
                previous is not None
                and sequence == previous_seq + 1
            ):
                c.setStrokeColor(palette[i])
                c.setLineWidth(1.6)
                c.setDash()
                c.line(*previous, px, py)

            c.setFillColor(palette[i])
            c.circle(px, py, 2.3, stroke=0, fill=1)


            previous = (px, py)
            previous_seq = sequence

        # Legend below the latency graph
        
        # Compact single-row legend below the latency chart
        legend_x = x + 25 + i * (width - 35) / 3
        legend_y = bottom - 29

        c.setStrokeColor(palette[i])
        c.setLineWidth(2)
        c.setDash()

        c.line(
            legend_x, legend_y,
            legend_x + 13, legend_y
        )

        _text(
            c, legend_x + 17, legend_y - 3,
            labels[i], 6.5, GREY
        )


def _response_chart(
    c: canvas.Canvas,
    x: float,
    y: float,
    width: float,
    height: float,
    tests: Sequence[Mapping[str, Any]] | None
) -> None:
        """Compare replies and unanswered packets across tests."""

        tests = list(tests or [])[:3]

        # Compact single-row legend below the packet-response chart.
        font_size = 7
        gap = 12

        replies_width = canvas_string_width(
            "Replies", "Helvetica", font_size
        )
        failed_width = canvas_string_width(
            "No response", "Helvetica", font_size
        )

        legend_width = (
            8 + 5 + replies_width +
            gap + 8 + 5 + failed_width
        )

        legend_x = x + width - legend_width / 2
        legend_y = y - height + 10

        c.setFillColor(VIOLET)
        c.rect(
            legend_x, legend_y, 8, 8,
            stroke=0, fill=1
        )
        _text(
            c, legend_x + 13, legend_y + 2,
            "Replies", font_size, GREY
        )

        second_x = legend_x + 13 + replies_width + gap

        c.setFillColor(MAGENTA)
        c.rect(
            second_x, legend_y, 8, 8,
            stroke=0, fill=1
        )
        _text(
            c, second_x + 13, legend_y + 2,
            "No response", font_size, GREY
        )

        if not tests:
            _text(
                c, x + 12, y - 70,
                "No ping test available.", 9, GREY
            )
            return

        # Actual saved reply counts per test
        counts = []

        for test in tests:
            sent, received, _, _ = _ping_metrics(test)
            counts.append((received, sent - received))

        left, right = x + 30, x + width - 10
        bottom, top = y - height + 39, y - 35

        maximum = max(
            4, *(sum(pair) for pair in counts)
        )

        # Grid and packet count labels
        for value in sorted({
            0, (maximum + 1) // 2, maximum
        }):
            grid_y = bottom + (
                value / maximum
            ) * (top - bottom)

            c.setStrokeColor(LINE)
            c.setLineWidth(0.5)
            c.line(left, grid_y, right, grid_y)

            _text(
                c, x + 5, grid_y - 3,
                str(value), 7, GREY
            )

        labels = ("Latest", "Previous 1", "Previous 2")

        group_width = (right - left) / len(counts)
        bar_width = min(19, group_width * 0.24)

        for i, (received, failed) in enumerate(counts):
            center = left + (i + 0.5) * group_width

            bars = (
                (center - bar_width - 2, received, VIOLET),
                (center + 2, failed, MAGENTA)
            )

            for bar_x, value, color in bars:
                bar_height = (
                    value / maximum
                ) * (top - bottom)

                c.setFillColor(color)
                c.rect(
                    bar_x, bottom,
                    bar_width, bar_height,
                    stroke=0, fill=1
                )

                c.setFillColor(NAVY)
                c.setFont("Helvetica-Bold", 6.7)
                c.drawCentredString(
                    bar_x + bar_width / 2,
                    bottom + bar_height + 5,
                    str(value)
                )

            c.setFillColor(GREY)
            c.setFont("Helvetica", 6.8)
            c.drawCentredString(
                center, bottom - 15, labels[i]
            )


def _report_header(
    c: canvas.Canvas,
    scan: Mapping[str, Any],
    logo_path: str | Path | None = None
) -> None:
    """UGNAY branding and centered report title."""

    if logo_path:
        try:
            image = Path(logo_path)
            if image.is_file():
                c.drawImage(
                    ImageReader(str(image)),
                    24, H - 66,
                    width=44, height=44,
                    preserveAspectRatio=True,
                    anchor="c",
                    mask="auto"
                )
        except (OSError, ValueError):
            pass

    # Branding at the upper-left corner
    _text(c, 76, H - 43, "UGNAY", 14, NAVY, True)
    _text(
        c, 76, H - 59,
        "Network Health Checker", 8, GREY
    )

    # Report title centered below the branding
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 17)
    c.drawCentredString(
        W / 2, H - 102,
        "Summary Report"
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
    _text(c, MARGIN, 704, "Device Info", 8, GREY)

    name = _fit_text(
        selected.get("name", "No device selected"),
        310, 12, "Helvetica-Bold"
    )
    _text(c, MARGIN, 675, name, 12, NAVY, True)

    # Trust badge
    trust = _str(selected.get("trust"), "Review")
    badge_x = min(
        MARGIN + canvas_string_width(
            name, "Helvetica-Bold", 12
        ) + 14,
        W - 112
    )

    c.setFillColor(colors.HexColor("#EAF0FB"))
    c.roundRect(
        badge_x, 670, 53, 16, 7,
        fill=1, stroke=0
    )
    _text(
        c, badge_x + 8, 675,
        _fit_text(trust, 39, 8), 8, BLUE
    )

    # Device details arranged in columns
    fields = [
        ("Hostname", selected.get("hostname"), MARGIN, 646),
        ("IP address", selected.get("ip_address"), 250, 646),
        ("Connected subnet", scan.get("subnet"), 446, 646),
        ("First discovered", _dt(
            selected.get("first_discovered")
        ), MARGIN, 604),
        ("Last scan response", _dt(
            selected.get("last_scan_response")
        ), 250, 604),
    ]

    for label, value, x, y in fields:
        _text(c, x, y, label, 8, GREY)

        available = W - MARGIN - x - 6

        if x == MARGIN:
            available = 180
        elif x == 250:
            available = 170

        _text(
            c, x, y - 15,
            _fit_text(value, available, 8.5),
            8.5, NAVY
        )

    # DEVICE CHARTS
    chart_width = (W - 2 * MARGIN - 14) / 2

    heading = "Device Latency Trend"

    if selected.get("name"):
        heading += f" ({selected['name']})"

    _text(
        c, MARGIN, 554,
        _fit_text(
            heading, chart_width,
            9.3, "Helvetica-Bold"
        ),
        9.3, NAVY, True
    )

    _latency_chart(
        c, MARGIN, 554,
        chart_width, 187, history[:3]
    )

    _text(
        c, MARGIN + chart_width + 14, 554,
        "Packet Responses",
        9.3, NAVY, True
    )

    _response_chart(
        c, MARGIN + chart_width + 14, 554,
        chart_width, 187, history[:3]
    )

    # DEVICE CONNECTIVITY SUMMARY
    _text(
        c, MARGIN, 342,
        "Device Connectivity Summary",
        12, NAVY, True
    )

    packets_sent = sum(
        len(test.get("replies") or [])
        for test in history
    )

    summary_lines = [
        f"Packets sent: {packets_sent}",
        f"Ping tests conducted: {len(history)}",
        (
            f"Latest test: "
            f"{_ms(latest.get('average_latency_ms'))} / "
            f"{_pct(latest.get('packet_loss_percent'))} loss"
            if latest else "Latest test: No test yet"
        ),
    ]

    for i, value in enumerate(summary_lines):
        _text(
            c, MARGIN + 8,
            320 - i * 17,
            "- " + value, 8.5, NAVY
        )


    # DEVICE CONNECTIVITY TEST LOGS
    _text(
        c, MARGIN, 240,
        "Device Connectivity Test Logs",
        12, NAVY, True
    )

    # Show up to 5 packets from the latest ping test.
    replies = _ping_replies(latest)
    visible_replies = replies[-5:]

    columns = [
        (MARGIN, "Packet"),
        (125, "Response"),
        (270, "Latency"),
        (375, "Test Time"),
    ]

    for x, heading in columns:
        _text(c, x, 215, heading, 8, GREY, True)

    c.setStrokeColor(LINE)
    c.setLineWidth(0.6)
    c.line(MARGIN, 206, W - MARGIN, 206)

    if not visible_replies:
        _text(
            c, MARGIN, 187,
            "No ping test logs available.",
            9, GREY
        )
    else:
        for index, reply in enumerate(visible_replies):
            y = 187 - index * 18

            latency_value = reply["latency_ms"]
            success = latency_value is not None

            values = [
                reply["sequence"],
                "Received" if success else "No response",
                f"{latency_value:.1f} ms" if success else "-",
                _dt(latest.get("tested_at")),
            ]

            for (x, _), value in zip(columns, values):
                _text(c, x, y, value, 8.5, NAVY)

        if len(replies) > 5:
            _text(
                c, MARGIN, 90,
                f"Showing the latest 5 of {len(replies)} packets "
                "from the most recent ping test.",
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
        c, MARGIN, 708,
        "Overall Network Assessment",
        12, NAVY, True
    )

    _text(
        c, MARGIN, 683,
        "Selected network scan, covering all discovered devices.",
        9, GREY
    )

    c.setStrokeColor(LINE)
    c.setLineWidth(0.5)
    c.line(MARGIN, 666, W - MARGIN, 666)

    # Overall network status
    health_color = (
        RED if health == "Needs attention"
        else AMBER if health in (
            "Partially tested", "Fair", "Not tested"
        )
        else GREEN if health == "Healthy"
        else GREY
    )

    _text(
        c, MARGIN, 639,
        f"Status: {health}",
        10, health_color, True
    )

    # Three network-wide metrics
    metrics = [
        (MARGIN, "Devices tested", f"{tested}/{total}"),
        (240, "Avg. latency", _ms(avg_latency)),
        (412, "Avg. loss", _pct(avg_loss)),
    ]

    for x, label, value in metrics:
        _text(c, x, 615, label, 8.5, GREY)
        _text(c, x, 594, value, 12, NAVY, True)

    c.setStrokeColor(LINE)
    c.line(MARGIN, 573, W - MARGIN, 573)

    # DISCOVERED DEVICES
    _text(
        c, MARGIN, 548,
        "Discovered Devices", 10, NAVY, True
    )

    # Reference layout: two columns only
    _text(c, MARGIN, 516, "Device Name", 8.5, BLUE)
    _text(c, 372, 516, "IP Address", 8.5, BLUE)

    shown_devices = devices[:8]

    for index, item in enumerate(shown_devices):
        y = 493 - index * 23

        _text(
            c, MARGIN, y,
            _fit_text(item.get("name"), 300, 8.5),
            8.5, NAVY
        )

        _text(
            c, 372, y,
            _fit_text(item.get("ip_address"), 130, 8.5),
            8.5, NAVY
        )

        # Thin row separators
        c.setStrokeColor(
            colors.HexColor("#EDF1F4")
        )
        c.setLineWidth(0.45)
        c.line(
            MARGIN, y - 8,
            W - MARGIN, y - 8
        )

    # Adjust position for longer device lists
    findings_y = (
        317 if len(shown_devices) <= 6
        else 317 - (len(shown_devices) - 6) * 23
    )

    if total > len(shown_devices):
        _text(
            c, MARGIN, findings_y + 13,
            f"Showing {len(shown_devices)} of {total} devices.",
            8, GREY
        )

    # CONNECTIVITY FINDINGS
    _text(
        c, MARGIN, findings_y,
        "Connectivity Findings",
        10, NAVY, True
    )

    if total == 0:
        finding = "No devices were discovered in this scan."
    elif tested == 0:
        finding = (
            "No devices have a saved ping test for this scan."
        )
    elif untested > 0:
        finding = (
            f"{untested} of {total} discovered devices "
            "remain untested."
        )
    else:
        finding = (
            "All discovered devices have saved ping tests."
        )

    high_loss_count = sum(
        (_number(ping.get("packet_loss_percent")) or 0) >= 10
        for _, ping in measured
    )

    high_latency_count = sum(
        (_number(ping.get("average_latency_ms")) or 0) >= 100
        for _, ping in measured
    )

    if high_loss_count or high_latency_count:
        finding += (
            f" High loss: {high_loss_count} device(s);"
            f" high latency: {high_latency_count} device(s)."
        )

    finding_end = _wrapped(
        c, finding,
        MARGIN, findings_y - 24,
        W - 2 * MARGIN,
        8.5, 13, NAVY
    )

    # GENERAL SECURITY RECOMMENDATIONS
    security_y = min(
        findings_y - 61,
        finding_end - 22
    )

    _text(
        c, MARGIN, security_y,
        "General Security Recommendations",
        10, NAVY, True
    )

    advice_end = _wrapped(
        c,
        "Use strong Wi-Fi passwords, update router firmware, "
        "and enable firewall protection.",
        MARGIN, security_y - 24,
        W - 2 * MARGIN,
        8.5, 13, NAVY
    )

    # REPORT NOTE
    divider_y = advice_end - 12

    c.setStrokeColor(LINE)
    c.line(
        MARGIN, divider_y,
        W - MARGIN, divider_y
    )

    _wrapped(
        c,
        "Network averages cover tested devices only. "
        "Security recommendations are general precautions, "
        "not detected vulnerabilities.",
        MARGIN, divider_y - 24,
        W - 2 * MARGIN,
        7.5, 11, GREY
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


