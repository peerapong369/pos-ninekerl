"""
Utilities for building PromptPay QR payloads reusable across the app.
"""

from __future__ import annotations

import base64
from io import BytesIO

import qrcode


def normalize_target(raw: str) -> str:
    """Normalize PromptPay target (phone number) into required numeric format."""
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) == 10 and digits.startswith("0"):
        digits = "0066" + digits[1:]
    if len(digits) not in (13, 15):
        raise ValueError("PromptPay target should be 10-digit phone or 13/15-digit ID")
    return digits


def _tag(tag: str, value: str) -> str:
    return f"{tag}{len(value):02d}{value}"


def build_promptpay_payload(target: str, amount: float | None = None) -> str:
    """Build EMVCo payload for PromptPay with optional fixed amount."""
    merchant_account = _tag("00", "A000000677010111") + _tag("01", target)

    payload = (
        _tag("00", "01")
        + _tag("01", "12" if amount else "11")
        + _tag("29", merchant_account)
        + _tag("52", "0000")
        + _tag("53", "764")
        + _tag("58", "TH")
        + _tag("59", "POS NineKerl")
        + _tag("60", "Bangkok")
    )

    if amount is not None:
        payload += _tag("54", f"{amount:.2f}")

    payload_without_crc = payload + "6304"
    crc = _crc16(payload_without_crc.encode("ascii"))
    payload += f"63{4:02d}{crc:04X}"
    return payload


def generate_qr_base64(payload: str) -> str:
    """Return QR code image (PNG) as base64 data URI."""
    qr = qrcode.QRCode(version=3, border=3)
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buffer = BytesIO()
    img.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _crc16(data: bytes) -> int:
    polynomial = 0x1021
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ polynomial
            else:
                crc <<= 1
            crc &= 0xFFFF
    return crc

