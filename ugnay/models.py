"""Shared contracts for the three members. No networking or calculations here."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class DeviceStatus(str, Enum):
    RESPONDING = "Responding"
    PACKET_LOSS = "Packet loss"
    UNREACHABLE = "Unreachable"
    NOT_TESTED = "Not tested"


@dataclass(frozen=True)
class NetworkInfo:
    local_ip: str
    subnet: str


@dataclass(frozen=True)
class PingReply:
    sequence: int
    latency_ms: Optional[float]  # None means this request timed out.


@dataclass(frozen=True)
class PingResult:
    ip_address: str
    tested_at: datetime
    replies: tuple[PingReply, ...]
    average_latency_ms: Optional[float]
    maximum_latency_ms: Optional[float]
    packet_loss_percent: float
    status: DeviceStatus


@dataclass(frozen=True)
class Device:
    ip_address: str
    hostname: Optional[str] = None
    kind: str = "computer"
    last_seen: Optional[datetime] = None
    result: Optional[PingResult] = None

    @property
    def display_name(self) -> str:
        return self.hostname or "Hostname unavailable"

    @property
    def status(self) -> DeviceStatus:
        return self.result.status if self.result else DeviceStatus.NOT_TESTED


@dataclass(frozen=True)
class DiscoveryResult:
    network: NetworkInfo
    scanned_at: datetime
    devices: tuple[Device, ...] = ()


@dataclass(frozen=True)
class Recommendation:
    title: str
    message: str
    severity: str = "info"  # info, success, warning, error


@dataclass(frozen=True)
class Report:
    report_id: str
    generated_at: datetime
    device_count: int
    average_latency_ms: Optional[float]
    packet_loss_percent: Optional[float]
    health: str
    text: str
    recommendations: tuple[Recommendation, ...] = field(default_factory=tuple)
