"""MEMBER 2: implement connectivity tests later. No ping commands run yet."""

from .models import Device, PingResult


class ConnectivityService:
    def test_connection(self, device: Device, count: int) -> PingResult:
        """TODO: ping, capture timeouts, and calculate latency and packet loss.

        Return one PingReply per request. A timeout uses latency_ms=None.
        An entirely unreachable host has None for both latency statistics,
        packet_loss_percent=100, and status=DeviceStatus.UNREACHABLE.
        """
        raise NotImplementedError("Member 2: implement ping tests and statistics.")
