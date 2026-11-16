
"""Member 2: Connectivity testing and network statistics for UGNAY."""

import ipaddress
import re
import subprocess
from datetime import datetime

from .models import Device, DeviceStatus, PingReply, PingResult


class ConnectivityService:
    """Run ICMP ping tests and calculate connectivity statistics."""

    ALLOWED_COUNTS = (4, 10, 20)
    TIMEOUT_MS = 1000

    @staticmethod
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

    def test_connection(self, device: Device, count: int) -> PingResult:
        """Ping a selected device and return its measured statistics."""

        if count not in self.ALLOWED_COUNTS:
            raise ValueError("Ping count must be 4, 10, or 20.")

        try:
            ip = ipaddress.ip_address(device.ip_address)
        except ValueError as exc:
            raise ValueError("Invalid device IP address.") from exc

        if ip.version != 4:
            raise ValueError("This version supports IPv4 devices only.")

        replies = []
        tested_at = datetime.now()

        for sequence in range(1, count + 1):
            try:
                # -n 1 sends one request.
                # -w 1000 waits up to 1000ms for a reply.
                # -4 explicitly uses IPv4.
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

                latency = None

                if completed.returncode == 0:
                    latency = self._parse_latency(
                        completed.stdout
                    )

                replies.append(
                    PingReply(
                        sequence=sequence,
                        latency_ms=latency,
                    )
                )

            except subprocess.TimeoutExpired:
                replies.append(
                    PingReply(
                        sequence=sequence,
                        latency_ms=None,
                    )
                )

            except FileNotFoundError as exc:
                raise RuntimeError(
                    "The Windows ping utility was not found."
                ) from exc

            except OSError as exc:
                raise RuntimeError(
                    f"Unable to execute ping: {exc}"
                ) from exc

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
