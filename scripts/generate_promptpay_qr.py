"""Generate PromptPay payment QR code for the restaurant."""

from __future__ import annotations

import argparse
from pathlib import Path

import qrcode


def format_phone(number: str) -> str:
    digits = "".join(filter(str.isdigit, number))
    if not digits or len(digits) not in (10, 13):
        raise ValueError("PromptPay เบอร์มือถือควรมี 10 หลัก (หรือโทรศัพท์สากล 13 หลัก)")
    if len(digits) == 10 and digits.startswith("0"):
        digits = "0066" + digits[1:]
    return digits


def build_promptpay_payload(target: str, amount: float | None = None) -> str:
    def _tag(tag: str, value: str) -> str:
        return f"{tag}{len(value):02d}{value}"

    merchant_account = _tag("00", "A000000677010111") + _tag("01", target)

    payload = (
        _tag("00", "01")  # Payload Format Indicator
        + _tag("01", "12" if amount else "11")  # 11 = static, 12 = dynamic (fixed amount)
        + _tag("29", merchant_account)
        + _tag("52", "0000")  # Merchant Category Code (optional -> set 0000)
        + _tag("53", "764")  # Currency code (764 = THB)
        + _tag("58", "TH")  # Country code
        + _tag("59", "POS NineKerl")  # Merchant name
        + _tag("60", "Bangkok")  # Merchant city
    )

    if amount is not None:
        payload += _tag("54", f"{amount:.2f}")

    payload_without_crc = payload + "6304"
    crc = crc16(payload_without_crc.encode("ascii"))
    payload += f"63{4:02d}{crc:04X}"
    return payload


def crc16(data: bytes) -> int:
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="สร้าง PromptPay QR Code สำหรับการชำระเงิน"
    )
    parser.add_argument(
        "--phone",
        default="0823293693",
        help="หมายเลข PromptPay (ค่าตั้งต้นเป็นเบอร์ร้าน)",
    )
    parser.add_argument(
        "--amount",
        type=float,
        default=None,
        help="กำหนดจำนวนเงินตายตัว (THB) ถ้าไม่ใส่ ลูกค้ากรอกเองได้",
    )
    parser.add_argument(
        "--output",
        default="qr_codes/promptpay.png",
        help="ตำแหน่งไฟล์ปลายทาง",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    phone = format_phone(args.phone)
    payload = build_promptpay_payload(phone, args.amount)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    qr = qrcode.QRCode(version=3, border=3)
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img.save(output_path)
    print(f"สร้าง QR พร้อมเพย์สำหรับ {phone} -> {output_path}")


if __name__ == "__main__":
    main()
