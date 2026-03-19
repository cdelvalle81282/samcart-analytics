"""Manager notification stubs — full implementation deferred to a future phase."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

import pandas as pd


class NotificationChannel(Enum):
    EMAIL = "email"
    SLACK = "slack"


class NotificationFrequency(Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


@dataclass
class ManagerConfig:
    name: str
    channel: NotificationChannel
    frequency: NotificationFrequency
    destination: str  # email address or Slack channel/webhook
    products: list[str] = field(default_factory=list)  # empty = all products


class NotificationSender(Protocol):
    def send(self, recipient: str, subject: str, body: str) -> None: ...


def format_daily_report(summary_df: pd.DataFrame, manager: ManagerConfig) -> str:
    """Format a daily summary into a human-readable report. Not yet implemented."""
    raise NotImplementedError("Manager notifications are not yet implemented.")


def dispatch_notifications(
    summary_df: pd.DataFrame,
    managers: list[ManagerConfig],
    sender: NotificationSender,
) -> None:
    """Send reports to all configured managers. Not yet implemented."""
    raise NotImplementedError("Manager notifications are not yet implemented.")
