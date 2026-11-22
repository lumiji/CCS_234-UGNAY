from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from ipaddress import IPv4Address, IPv4Interface, ip_address, ip_network
import json
from math import isfinite
from pathlib import Path
import subprocess
import sys

from .models import Device, DiscoveryResult, NetworkInfo


# Read adapter metadata with the native IP Helper API, bypassing slow or
# restricted PowerShell/CIM providers. Isolation keeps an OS stall killable.
_NETWORK_HELPER = Path(__file__).with_name("windows_network.py").resolve()

# A lightweight interpreter calls Windows' native ICMP API. The file is run in
# isolation so an OS/backend stall still has a killable process deadline.
_PROBE_HELPER = Path(__file__).with_name("icmp_probe.py").resolve()

# Isolate the OS resolver so a slow reverse lookup can be killed at its deadline.
# A Future timeout or socket.setdefaulttimeout() cannot bound gethostbyaddr().
_HOSTNAME_QUERY = """
import json
import socket
import sys

try:
    hostname = socket.gethostbyaddr(sys.argv[1])[0]
except OSError:
    hostname = None
print(json.dumps(hostname))
"""

# Windows IPStatus values that mean the target did not return an echo reply.
# Resource, hardware, invalid-request, and unknown statuses must fail the scan.
_ICMP_NO_RESPONSE_STATUSES = frozenset({
    11002,  # DestinationNetworkUnreachable
    11003,  # DestinationHostUnreachable
    11004,  # DestinationProtocolUnreachable
    11005,  # DestinationPortUnreachable
    11010,  # TimedOut
    11013,  # TtlExpired
    11014,  # TtlReassemblyTimeExceeded
    11040,  # DestinationUnreachable
    11041,  # TimeExceeded
})


class NetworkDetectionError(RuntimeError):
    """The local adapter configuration could not produce a usable IPv4 network."""


class NetworkScanError(RuntimeError):
    """Discovery could not execute reliably; this is not an empty scan result."""


# Detect the local IPv4 subnet on Windows and 
# find devices that respond to ping in the requested range.
class DiscoveryService:
    def __init__(self, *, interface_alias: str | None = None, max_workers: int = 8,
                 icmp_timeout_ms: int = 1000, process_timeout: float = 15.0,
                 hostname_timeout: float = 2.0, max_hosts: int = 1024):
        if interface_alias is not None and (
            not isinstance(interface_alias, str) or not interface_alias.strip()
        ):
            raise ValueError("interface_alias must be a nonempty interface name.")
        for name, value in (("max_workers", max_workers), ("max_hosts", max_hosts),
                            ("icmp_timeout_ms", icmp_timeout_ms)):
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer.")
        if icmp_timeout_ms > 2**31 - 1:
            raise ValueError("icmp_timeout_ms exceeds the Windows ICMP timeout limit.")
        for name, value in (("process_timeout", process_timeout), ("hostname_timeout", hostname_timeout)):
            if type(value) not in (int, float) or not isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be a positive, finite number of seconds.")
        if process_timeout < icmp_timeout_ms / 1000 + 1:
            raise ValueError("process_timeout must allow at least 1 second of overhead beyond the ICMP timeout.")
        self.interface_alias = interface_alias
        self.max_workers = max_workers
        self.icmp_timeout_ms = icmp_timeout_ms
        self.process_timeout = process_timeout
        self.hostname_timeout = hostname_timeout
        self.max_hosts = max_hosts
        self._network: NetworkInfo | None = None

    def detect_network(self) -> NetworkInfo:
        """Read a connected Windows interface's actual IPv4 address and prefix.

        An explicit interface_alias is matched literally, ignoring case. Otherwise
        prefer physical Ethernet/Wi-Fi, then non-link-local addresses, lower IPv4
        interface metrics, lower interface indices, and lower numeric IPs. No
        gateway, DNS lookup, or internet connection is required. Link-local IPv4
        remains usable for an isolated LAN when no better address is available.
        """

        self._network = None
        if sys.platform != "win32":
            raise NetworkDetectionError("Local network detection currently supports Windows only.")

        try:
            completed = subprocess.run(
                [sys.executable, "-I", "-X", "utf8", str(_NETWORK_HELPER)],
                capture_output=True,
                encoding="utf-8",
                check=True,
                timeout=60,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except subprocess.TimeoutExpired as error:
            raise NetworkDetectionError("The native Windows network configuration helper timed out. Try scanning again.") from error
        except subprocess.CalledProcessError as error:
            detail = (error.stderr or "").strip().splitlines()
            message = "Windows could not read network configuration"
            if detail:
                message += f": {detail[0]}"
            raise NetworkDetectionError(message) from error
        except OSError as error:
            raise NetworkDetectionError(f"Could not start Windows network detection: {error}") from error
        except UnicodeError as error:
            raise NetworkDetectionError("Windows returned unreadable network configuration.") from error

        try:
            records = json.loads(completed.stdout)
        except (ValueError, TypeError) as error:
            raise NetworkDetectionError("Windows returned invalid network configuration JSON.") from error
        if isinstance(records, dict):
            records = [records]
        if not isinstance(records, list) or any(not isinstance(row, dict) for row in records):
            raise NetworkDetectionError("Windows returned an unexpected network configuration format.")

        candidates = []
        for row in records:
            try:
                alias = row["InterfaceAlias"]
                if not isinstance(alias, str):
                    raise ValueError("Invalid interface name")
                if self.interface_alias is not None and alias.casefold() != self.interface_alias.casefold():
                    continue
                if row["Status"] != "Up" or row["InterfaceType"] == 24:
                    continue
                if row["AddressState"] != "Preferred" or row["SkipAsSource"] is not False:
                    continue

                address = ip_address(row["IPAddress"])
                if address.version != 4 or address.is_loopback or address.is_unspecified or address.is_multicast:
                    continue
                if str(address) == "255.255.255.255":
                    continue
                prefix = row["PrefixLength"]
                metric = row["InterfaceMetric"]
                index = row["InterfaceIndex"]
                interface_type = row["InterfaceType"]
                hardware = row["HardwareInterface"]
                if (type(prefix) is not int or not 0 <= prefix <= 32
                        or type(metric) is not int or metric < 0
                        or type(index) is not int or index < 1
                        or type(interface_type) is not int or interface_type < 1
                        or type(hardware) is not bool):
                    raise ValueError("Invalid interface metadata")

                interface = IPv4Interface(f"{address}/{prefix}")
                physical_lan = hardware and interface_type in (6, 71)
                priority = (not physical_lan, address.is_link_local, metric, index, int(address))
                candidates.append((priority, NetworkInfo(str(address), str(interface.network))))
            except (KeyError, ValueError, TypeError) as error:
                raise NetworkDetectionError("Windows returned invalid IPv4 interface data.") from error

        if not candidates:
            if self.interface_alias is not None:
                raise NetworkDetectionError(
                    f"No connected interface named {self.interface_alias!r} has a usable IPv4 address."
                )
            raise NetworkDetectionError("No connected network adapter with a usable IPv4 address was found.")
        self._network = min(candidates, key=lambda candidate: candidate[0])[1]
        return self._network

    def scan_network(self, subnet: str) -> DiscoveryResult:
        """Return ICMP responders and optional hostnames in an IPv4 CIDR range.

        Host bits are normalized to the supplied prefix, never shortened to /24.
        Use the latest detected local IP, detecting it first if necessary. The
        returned NetworkInfo.subnet describes the requested scan range. A valid
        scan with no responders returns devices=(); execution failures raise.
        """
        if not isinstance(subnet, str):
            raise ValueError("The subnet must be an IPv4 network in CIDR notation.")
        try:
            network = ip_network(subnet, strict=False)
        except ValueError as error:
            raise ValueError(f"Invalid IPv4 subnet: {subnet!r}.") from error
        if network.version != 4:
            raise ValueError("Device discovery supports IPv4 subnets only.")
        host_count = network.num_addresses if network.prefixlen >= 31 else network.num_addresses - 2
        if host_count > self.max_hosts:
            raise ValueError(
                f"Subnet {network} contains {host_count:,} candidate hosts, exceeding "
                f"the configured limit of {self.max_hosts:,}. Choose a smaller range "
                "or explicitly increase max_hosts."
            )
        if sys.platform != "win32":
            raise NetworkScanError("Device discovery currently supports Windows only.")

        detected = self._network if self._network is not None else self.detect_network()
        devices_by_ip: dict[str, Device] = {}
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

        devices = tuple(sorted(devices_by_ip.values(), key=lambda device: int(IPv4Address(device.ip_address))))
        return DiscoveryResult(
            network=NetworkInfo(local_ip=detected.local_ip, subnet=str(network)),
            scanned_at=datetime.now().astimezone(),
            devices=devices,
        )

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

    def _probe_host(self, ip_address: str) -> bool:
        """Send one ICMP echo; only IPStatus.Success from the target counts."""
        address = str(IPv4Address(ip_address))
        if sys.platform != "win32":
            raise NetworkScanError("Device discovery currently supports Windows only.")
        for attempt in range(2):
            try:
                completed = subprocess.run(
                    [sys.executable, "-I", "-X", "utf8", str(_PROBE_HELPER)],
                    input=json.dumps({"IPAddress": address, "TimeoutMs": self.icmp_timeout_ms}),
                    capture_output=True,
                    encoding="utf-8",
                    check=True,
                    timeout=self.process_timeout,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                break
            except subprocess.TimeoutExpired as error:
                # subprocess.run kills/reaps the old helper before a fresh retry.
                # Do not turn an execution failure into a nonresponding device.
                if attempt:
                    raise NetworkScanError(
                        f"The ICMP probe helper for {address} exceeded {self.process_timeout:g}s "
                        "on both attempts. Check local system load or application restrictions."
                    ) from error
            except subprocess.CalledProcessError as error:
                detail = (error.stderr or "").strip().splitlines()
                message = f"Windows could not execute the ICMP probe for {address}"
                if detail:
                    message += f": {detail[0]}"
                raise NetworkScanError(message) from error
            except (OSError, UnicodeError) as error:
                raise NetworkScanError(f"Could not run the ICMP probe for {address}: {error}") from error

        try:
            reply = json.loads(completed.stdout)
            if not isinstance(reply, dict) or type(reply.get("Status")) is not int:
                raise ValueError("Missing ICMP status")
            # IPStatus.Success == 0. The process exit code alone is insufficient.
            if reply["Status"] in _ICMP_NO_RESPONSE_STATUSES:
                return False
            if reply["Status"] != 0:
                raise NetworkScanError(
                    f"The ICMP backend failed for {address} (Windows status {reply['Status']})."
                )
            return IPv4Address(reply["Address"]) == IPv4Address(address)
        except (KeyError, TypeError, ValueError) as error:
            raise NetworkScanError(f"The ICMP probe for {address} returned invalid response data.") from error

    def _resolve_hostname(self, ip_address: str) -> str | None:
        """Best-effort reverse lookup with a killable process and a hard timeout."""
        address = str(IPv4Address(ip_address))
        try:
            completed = subprocess.run(
                [sys.executable, "-I", "-c", _HOSTNAME_QUERY, address],
                capture_output=True,
                encoding="utf-8",
                check=True,
                timeout=self.hostname_timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            hostname = json.loads(completed.stdout)
        except (OSError, subprocess.SubprocessError, ValueError, TypeError):
            return None
        if isinstance(hostname, str) and hostname.strip() and hostname.strip() != address:
            return hostname.strip()
        return None
