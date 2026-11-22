"""Member 3: generate network reports, recommendations, and text exports."""

from datetime import datetime
from pathlib import Path

from .models import Device, DeviceStatus, NetworkInfo, Recommendation, Report


class ReportingService:
    """Turn discovery and ping results into a readable network health report."""

    HIGH_LATENCY_MS = 100.0
    FAIR_LATENCY_MS = 50.0
    HIGH_PACKET_LOSS_PERCENT = 10.0

    def generate_report(
        self, network: NetworkInfo, devices: tuple[Device, ...], generated_at: datetime
    ) -> Report:
        """Combine available scan/ping results into a dated, plain-text report."""
        tested = [device for device in devices if device.result is not None]
        latencies = [
            device.result.average_latency_ms
            for device in tested
            if device.result.average_latency_ms is not None
        ]
        losses = [device.result.packet_loss_percent for device in tested]

        # Unweighted device averages: each tested device contributes equally.
        average_latency = sum(latencies) / len(latencies) if latencies else None
        packet_loss = sum(losses) / len(losses) if losses else None

        if not devices:
            health = "No devices detected"
        elif not tested:
            health = "Not tested"
        elif any(
            device.result.status == DeviceStatus.UNREACHABLE
            or device.result.packet_loss_percent >= self.HIGH_PACKET_LOSS_PERCENT
            or (
                device.result.average_latency_ms is not None
                and device.result.average_latency_ms >= self.HIGH_LATENCY_MS
            )
            for device in tested
        ):
            health = "Needs attention"
        elif any(
            device.result.status == DeviceStatus.PACKET_LOSS
            or device.result.packet_loss_percent > 0
            or (
                device.result.average_latency_ms is not None
                and device.result.average_latency_ms >= self.FAIR_LATENCY_MS
            )
            for device in tested
        ):
            health = "Fair"
        elif len(tested) != len(devices):
            health = "Partially tested"
        else:
            health = "Healthy"

        recommendations = self.get_recommendations(devices)
        report_id = generated_at.strftime("RPT-%Y%m%d-%H%M%S-%f")

        lines = [
            "LAN HEALTH CHECKER - NETWORK REPORT",
            "=" * 42,
            f"Report ID: {report_id}",
            f"Generated at: {generated_at:%Y-%m-%d %H:%M:%S}",
            f"Local IP address: {network.local_ip}",
            f"Network subnet: {network.subnet}",
            "",
            "NETWORK PERFORMANCE SUMMARY",
            "-" * 42,
            f"Devices detected: {len(devices)}",
            f"Devices tested: {len(tested)}",
            f"Network health: {health}",
            f"Average latency across devices: {self._ms(average_latency)}",
            f"Average packet loss across devices: {self._pct(packet_loss)}",
            "",
            "DEVICE AND PING RESULTS",
            "-" * 42,
        ]

        if not devices:
            lines.append("No devices are available to include in this report.")

        for index, device in enumerate(devices, start=1):
            lines.extend(
                [
                    f"{index}. {device.display_name}",
                    f"   IP address: {device.ip_address}",
                    f"   Status: {device.status.value}",
                ]
            )
            result = device.result
            if result is None:
                lines.append("   No ping results available.")