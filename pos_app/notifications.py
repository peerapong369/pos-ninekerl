from __future__ import annotations

import os
import threading
from email.message import EmailMessage
from typing import Dict, Optional

from flask import current_app
from linebot import LineBotApi
from linebot.models import TextSendMessage

from .models import Order


def notify_new_order(order: Order) -> None:
    """Dispatch notifications for a newly created order.

    This function spawns a background thread so HTTP responses are not blocked.
    """

    config = _load_config()
    if not config:
        return

    summary = _build_order_summary(order)
    if not summary:
        return

    logger = None
    try:
        logger = current_app.logger  # type: ignore[attr-defined]
    except RuntimeError:
        logger = None

    thread = threading.Thread(
        target=_send_notifications,
        args=(summary, config, logger),
        daemon=True,
    )
    thread.start()


def _load_config() -> Dict[str, Optional[str]]:
    """Read notification configuration from environment variables."""

    config = {
        "email_to": os.getenv("NOTIFY_EMAIL_TO"),
        "email_from": os.getenv("NOTIFY_EMAIL_FROM"),
        "smtp_host": os.getenv("SMTP_HOST"),
        "smtp_port": os.getenv("SMTP_PORT"),
        "smtp_username": os.getenv("SMTP_USERNAME"),
        "smtp_password": os.getenv("SMTP_PASSWORD"),
        "smtp_use_tls": os.getenv("SMTP_USE_TLS", "true").lower() in {"true", "1", "yes"},
        "line_channel_token": os.getenv("LINE_CHANNEL_ACCESS_TOKEN"),
        "line_user_ids": os.getenv("LINE_USER_IDS"),
    }

    if not config["email_to"] and not config["line_channel_token"]:
        return {}
    return config


def _build_order_summary(order: Order) -> Dict[str, object]:
    try:
        items = [
            {
                "name": item.menu_item.name,
                "quantity": item.quantity,
                "price": float(item.menu_item.price),
            }
            for item in order.items
        ]
        return {
            "id": order.id,
            "table": order.table.name,
            "table_code": order.table.code,
            "status": order.status,
            "total": order.grand_total,
            "items": items,
        }
    except Exception:
        return {}


def _send_notifications(
    summary: Dict[str, object],
    config: Dict[str, Optional[str]],
    logger,
) -> None:
    if config.get("email_to") and config.get("smtp_host"):
        try:
            _send_email(summary, config)
        except Exception as exc:  # pragma: no cover - best effort logging
            if logger:
                logger.warning("Failed to send order email notification: %s", exc)
    if config.get("line_channel_token"):
        try:
            _send_line_message(summary, config)
        except Exception as exc:  # pragma: no cover
            if logger:
                logger.warning("Failed to send LINE messaging notification: %s", exc)


def _send_email(summary: Dict[str, object], config: Dict[str, Optional[str]]) -> None:
    import smtplib

    smtp_host = config["smtp_host"]
    smtp_port = int(config.get("smtp_port") or 587)
    smtp_username = config.get("smtp_username")
    smtp_password = config.get("smtp_password")
    smtp_use_tls = bool(config.get("smtp_use_tls"))

    email_to = [addr.strip() for addr in (config.get("email_to") or "").split(",") if addr.strip()]
    if not email_to:
        return

    email_from = config.get("email_from") or (smtp_username or "pos@localhost")
    subject = f"[NineKerl POS] ออเดอร์ใหม่ #{summary['id']} โต๊ะ {summary['table_code']}"

    lines = [
        f"มีออเดอร์ใหม่จากโต๊ะ {summary['table']} (#{summary['id']})",
        "",
        "รายการอาหาร:",
    ]
    for item in summary["items"]:  # type: ignore[assignment]
        lines.append(f"- {item['name']} x {item['quantity']}")
    lines.append("")
    lines.append(f"ยอดรวม: {summary['total']:.2f} บาท")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = email_from
    message["To"] = ", ".join(email_to)
    message.set_content("\n".join(lines))

    if smtp_use_tls:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            if smtp_username and smtp_password:
                server.login(smtp_username, smtp_password)
            server.send_message(message)
    else:
        with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
            if smtp_username and smtp_password:
                server.login(smtp_username, smtp_password)
            server.send_message(message)


def _send_line_message(summary: Dict[str, object], config: Dict[str, Optional[str]]) -> None:
    channel_token = config.get("line_channel_token")
    if not channel_token:
        return

    user_ids_raw = config.get("line_user_ids", "")
    user_ids = [user_id.strip() for user_id in user_ids_raw.split(",") if user_id.strip()]

    items_text = "\n".join(
        f"- {item['name']} x {item['quantity']}" for item in summary["items"]  # type: ignore
    )
    message = TextSendMessage(
        f"🍜 ออเดอร์ใหม่ #{summary['id']}\n"
        f"โต๊ะ: {summary['table']} ({summary['table_code']})\n"
        f"{items_text}\n"
        f"ยอดรวม: {summary['total']:.2f} บาท"
    )

    line_api = LineBotApi(channel_token)
    if not user_ids:
        line_api.broadcast(message)
        return

    chunks = [user_ids[i : i + 500] for i in range(0, len(user_ids), 500)]
    for chunk in chunks:
        line_api.multicast(chunk, message)
