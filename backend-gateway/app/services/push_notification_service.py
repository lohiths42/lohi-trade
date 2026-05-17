"""Push notification service for Firebase Cloud Messaging (FCM).

Sends push notifications to mobile devices for:
- Trade alerts (signal triggers, position opens/closes)
- Order updates (filled, cancelled, rejected)
- Kill switch activations/deactivations

Requirements: 12.6
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class NotificationType(str, Enum):
    """Categories of push notifications."""

    TRADE_ALERT = "trade_alert"
    ORDER_UPDATE = "order_update"
    KILL_SWITCH = "kill_switch"


@dataclass
class PushNotification:
    """A push notification to be sent via FCM."""

    user_id: str
    title: str
    body: str
    notification_type: NotificationType
    data: dict = field(default_factory=dict)


class PushNotificationService:
    """Firebase Cloud Messaging push notification service.

    In production, this connects to the FCM HTTP v1 API. For development
    and testing, notifications are logged and stored in an internal list.
    """

    def __init__(self, fcm_credentials: Optional[dict] = None):
        self._fcm_credentials = fcm_credentials
        self._sent_notifications: list[PushNotification] = []
        self._device_tokens: dict[str, list[str]] = {}  # user_id → [device_tokens]

    def register_device(self, user_id: str, device_token: str) -> None:
        """Register a device token for push notifications."""
        if user_id not in self._device_tokens:
            self._device_tokens[user_id] = []
        if device_token not in self._device_tokens[user_id]:
            self._device_tokens[user_id].append(device_token)
            logger.info("FCM device registered: user=%s", user_id)

    def unregister_device(self, user_id: str, device_token: str) -> None:
        """Unregister a device token."""
        if user_id in self._device_tokens:
            self._device_tokens[user_id] = [
                t for t in self._device_tokens[user_id] if t != device_token
            ]

    async def send_notification(self, notification: PushNotification) -> bool:
        """Send a push notification to all registered devices for a user.

        Returns True if at least one device was notified.
        """
        self._sent_notifications.append(notification)
        tokens = self._device_tokens.get(notification.user_id, [])

        if not tokens:
            logger.debug(
                "FCM skip: no devices for user=%s type=%s",
                notification.user_id,
                notification.notification_type.value,
            )
            return False

        for token in tokens:
            await self._send_to_device(token, notification)

        logger.info(
            "FCM sent: user=%s type=%s devices=%d title=%s",
            notification.user_id,
            notification.notification_type.value,
            len(tokens),
            notification.title,
        )
        return True

    async def _send_to_device(self, device_token: str, notification: PushNotification) -> bool:
        """Send notification to a single device via FCM HTTP v1 API.

        In production, this would make an HTTP POST to
        https://fcm.googleapis.com/v1/projects/{project}/messages:send
        """
        # Production implementation would use httpx/aiohttp to call FCM API
        # For now, log the notification
        logger.debug(
            "FCM → device=%s title=%s body=%s",
            device_token[:8] + "...",
            notification.title,
            notification.body[:50],
        )
        return True

    # ── Convenience methods for specific notification types ──────────────

    async def notify_trade_alert(
        self,
        user_id: str,
        symbol: str,
        action: str,
        price: float,
        strategy: str = "",
    ) -> bool:
        """Send trade alert notification (signal trigger, position open/close)."""
        return await self.send_notification(
            PushNotification(
                user_id=user_id,
                title=f"Trade Alert: {symbol}",
                body=f"{action} {symbol} at ₹{price:.2f}" + (f" ({strategy})" if strategy else ""),
                notification_type=NotificationType.TRADE_ALERT,
                data={
                    "symbol": symbol,
                    "action": action,
                    "price": str(price),
                    "strategy": strategy,
                },
            )
        )

    async def notify_order_update(
        self,
        user_id: str,
        order_id: str,
        symbol: str,
        status: str,
        details: str = "",
    ) -> bool:
        """Send order status update notification (filled, cancelled, rejected)."""
        return await self.send_notification(
            PushNotification(
                user_id=user_id,
                title=f"Order {status}: {symbol}",
                body=f"Order {order_id[:8]} for {symbol} is {status}"
                + (f". {details}" if details else ""),
                notification_type=NotificationType.ORDER_UPDATE,
                data={
                    "order_id": order_id,
                    "symbol": symbol,
                    "status": status,
                },
            )
        )

    async def notify_kill_switch(
        self,
        user_id: str,
        activated: bool,
        reason: str = "",
    ) -> bool:
        """Send kill switch activation/deactivation notification."""
        action = "ACTIVATED" if activated else "DEACTIVATED"
        return await self.send_notification(
            PushNotification(
                user_id=user_id,
                title=f"Kill Switch {action}",
                body=f"Trading kill switch has been {action.lower()}"
                + (f". Reason: {reason}" if reason else ""),
                notification_type=NotificationType.KILL_SWITCH,
                data={
                    "activated": str(activated).lower(),
                    "reason": reason,
                },
            )
        )

    @property
    def sent_notifications(self) -> list[PushNotification]:
        """Access sent notifications (useful for testing)."""
        return list(self._sent_notifications)

    def clear_sent(self) -> None:
        """Clear sent notification history (useful for testing)."""
        self._sent_notifications.clear()
