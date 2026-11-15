"""MEMBER 3: reporting and recommendation integration points; no file writes."""

from datetime import datetime
from pathlib import Path

from .models import Device, NetworkInfo, Recommendation, Report


class ReportingService:
    def generate_report(
        self, network: NetworkInfo, devices: tuple[Device, ...], generated_at: datetime
    ) -> Report:
        """TODO: combine scan and ping results into a dated plain-text report."""
        raise NotImplementedError("Member 3: implement report generation and summaries.")

    def get_recommendations(self, devices: tuple[Device, ...]) -> tuple[Recommendation, ...]:
        """TODO: connectivity alerts, unreachable hosts, firewall/password reminders."""
        raise NotImplementedError("Member 3: implement recommendations.")

    def export_report(self, report: Report, destination: Path) -> None:
        """TODO: write report.text as UTF-8, and handle filesystem errors."""
        raise NotImplementedError("Member 3: implement text report export.")
