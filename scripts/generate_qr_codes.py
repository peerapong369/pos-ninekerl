"""สร้าง QR Code สำหรับแต่ละโต๊ะ"""

from __future__ import annotations

import argparse
from pathlib import Path

import qrcode

from pos_app import create_app
from pos_app.database import db_session
from pos_app.models import DiningTable


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="สร้างไฟล์ QR Code สำหรับโต๊ะในร้าน"
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:5000/table/{table_code}",
        help="ลิงก์พื้นฐานสำหรับเมนูโต๊ะ ใช้ {table_code} เป็นตัวแปร",
    )
    parser.add_argument(
        "--output",
        default="qr_codes",
        help="โฟลเดอร์ปลายทางสำหรับบันทึกไฟล์ภาพ PNG",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    create_app()  # Ensure database is ready

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    tables = db_session.query(DiningTable).order_by(DiningTable.code).all()

    if not tables:
        print("ไม่พบข้อมูลโต๊ะในระบบ")
        return

    for table in tables:
        url = args.base_url.format(table_code=table.code)
        img = qrcode.make(url)
        filename = output_dir / f"{table.code}.png"
        img.save(filename)
        print(f"สร้าง QR สำหรับ {table.name} -> {filename}")


if __name__ == "__main__":
    main()
