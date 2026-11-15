"""MEMBER 1: implement these methods later. They are intentionally inert."""

from .models import DiscoveryResult, NetworkInfo


class DiscoveryService:
    def detect_network(self) -> NetworkInfo:
        """TODO: detect local IPv4 address and actual subnet (do not assume /24)."""
        raise NotImplementedError("Member 1: implement local IP and subnet detection.")

    def scan_network(self, subnet: str) -> DiscoveryResult:
        """TODO: discover hosts, resolve names, and return an empty tuple if none.

        Raise an appropriate exception for scan failures. Keep this work off the
        Tk thread when integrating it; publish results with the app's UI queue.
        """
        raise NotImplementedError("Member 1: implement network discovery and hostname lookup.")
