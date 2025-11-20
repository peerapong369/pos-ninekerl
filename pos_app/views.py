from __future__ import annotations

import io
from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple
import secrets

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    session,
    url_for,
)
import csv
import qrcode
import json
import urllib.parse
from PIL import Image, ImageDraw, ImageFont
from linebot import LineBotApi, WebhookParser
from linebot.exceptions import InvalidSignatureError, LineBotApiError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload
from werkzeug.utils import secure_filename

from .database import db_session

BASE_DIR = Path(__file__).resolve().parent.parent
from .models import (
    DiningTable,
    Ingredient,
    Invoice,
    MenuCategory,
    MenuItem,
    MenuItemIngredient,
    MenuOptionGroup,
    MenuOption,
    Order,
    OrderItem,
    OrderStatusEnum,
    Payment,
    PaymentMethodEnum,
    Setting,
    StockMovement,
    StockMovementTypeEnum,
    seed_sample_data,
)
from .promptpay import build_promptpay_payload, generate_qr_base64, normalize_target
from .auth import login_required
from . import notifications

main_blueprint = Blueprint("main", __name__)

STATUS_LABELS = {
    OrderStatusEnum.PENDING.value: "รอทำ",
    OrderStatusEnum.IN_PROGRESS.value: "กำลังทำ",
    OrderStatusEnum.COMPLETED.value: "เสิร์ฟแล้ว",
    OrderStatusEnum.PAID.value: "ชำระเงินแล้ว",
}

STATUS_HINTS = {
    OrderStatusEnum.PENDING.value: "ออเดอร์ของคุณถูกส่งไปที่ครัวแล้ว กำลังรอเชฟเริ่มทำ",
    OrderStatusEnum.IN_PROGRESS.value: "เชฟกำลังปรุงเมนูของคุณ โปรดรอสักครู่",
    OrderStatusEnum.COMPLETED.value: "ออเดอร์เสร็จแล้ว เตรียมเสิร์ฟถึงโต๊ะของคุณ",
    OrderStatusEnum.PAID.value: "เช็คบิลเรียบร้อยแล้ว ขอบคุณที่ใช้บริการค่ะ",
}

PAYMENT_METHOD_LABELS = {
    PaymentMethodEnum.CASH.value: "เงินสด",
    PaymentMethodEnum.PROMPTPAY.value: "PromptPay",
    PaymentMethodEnum.CARD.value: "บัตรเครดิต/เดบิต",
    PaymentMethodEnum.TRANSFER.value: "โอนเงิน",
}

INVOICE_TAX_RATE = Decimal("0.07")
INVOICE_TAX_PERCENT = Decimal("7.00")

_BASE_NOODLE_CHOICES = ["เล็ก", "ใหญ่", "หมี่ขาว", "เส้นหมี่เหลือง", "วุ้นเส้น"]
_BASE_EXTRA_OPTIONS = [
    {"id": "extra_red_pork", "label": "เพิ่มหมูแดง +10 บาท", "name": "เพิ่มหมูแดง", "price": 10},
    {"id": "extra_soft_pork", "label": "เพิ่มหมูนุ่ม +10 บาท", "name": "เพิ่มหมูนุ่ม", "price": 10},
    {"id": "extra_egg", "label": "เพิ่มไข่ +10 บาท", "name": "เพิ่มไข่", "price": 10},
]

SPECIAL_MENU_CONFIG = {
    "ก๋วยเตี๋ยวตำยำสุโขทัยสูตรดั่งเดิม (แบบน้ำ)": {
        "image": "images/noodle_soup.svg",
        "image_alt": "ก๋วยเตี๋ยวตำยำสุโขทัยแบบน้ำ",
        "noodles": _BASE_NOODLE_CHOICES,
        "extras": _BASE_EXTRA_OPTIONS,
    },
    "ก๋วยเตี๋ยวตำยำสุโขทัยสูตรดั่งเดิม (แบบแห้ง)": {
        "image": "images/noodle_dry.svg",
        "image_alt": "ก๋วยเตี๋ยวตำยำสุโขทัยแบบแห้ง",
        "noodles": _BASE_NOODLE_CHOICES,
        "extras": _BASE_EXTRA_OPTIONS,
    },
}


def _promptpay_config() -> Tuple[str | None, str | None]:
    """Return configured PromptPay target and normalized value (if valid)."""
    stored = db_session.scalar(
        select(Setting.value).where(Setting.key == "promptpay_target")
    )
    raw_target = stored or current_app.config.get("PROMPTPAY_TARGET")
    if not raw_target:
        return None, None
    try:
        normalized = normalize_target(raw_target)
    except ValueError:
        return raw_target, None
    return raw_target, normalized


def _get_game_target(default: int = 239) -> int:
    value = db_session.scalar(select(Setting.value).where(Setting.key == "game_target"))
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _get_store_hours() -> Dict[str, Dict[str, str | bool]]:
    raw = db_session.scalar(select(Setting.value).where(Setting.key == "store_hours"))
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _save_store_hours(hours: Dict[str, Dict[str, str | bool]]) -> None:
    payload = json.dumps(hours, ensure_ascii=False)
    setting = db_session.query(Setting).filter(Setting.key == "store_hours").one_or_none()
    if setting:
        setting.value = payload
    else:
        db_session.add(Setting(key="store_hours", value=payload))
    db_session.commit()


def _get_auth_password(role: str) -> str | None:
    key = f"auth_{role}_password"
    setting = db_session.query(Setting).filter(Setting.key == key).one_or_none()
    return setting.value if setting and setting.value else None


def _set_auth_password(role: str, password: str) -> None:
    key = f"auth_{role}_password"
    setting = db_session.query(Setting).filter(Setting.key == key).one_or_none()
    if setting:
        setting.value = password
    else:
        db_session.add(Setting(key=key, value=password))
    db_session.commit()


def _store_timezone() -> ZoneInfo:
    tz_name = current_app.config.get("STORE_TIMEZONE", "Asia/Bangkok")
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo("UTC")


def _store_status(now: datetime | None = None) -> Dict[str, str | bool | None]:
    tz = _store_timezone()
    now = now or datetime.now(tz)
    hours = _get_store_hours()
    if not hours:
        return {
            "open": True,
            "next_open": None,
            "current_time": now.strftime("%H:%M"),
            "timezone": tz.key,
        }
    weekday_keys = [
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    ]
    today_key = weekday_keys[now.weekday()]

    def parse_time(value: str | None):
        if not value:
            return None
        try:
            return datetime.strptime(value, "%H:%M").time()
        except ValueError:
            return None

    info_today = hours.get(today_key, {}) if isinstance(hours, dict) else {}
    open_now = False
    next_open_label = None

    if info_today.get("open"):
        start_t = parse_time(info_today.get("start"))
        end_t = parse_time(info_today.get("end"))
        if start_t and end_t:
            today_start = now.replace(hour=start_t.hour, minute=start_t.minute, second=0, microsecond=0)
            today_end = now.replace(hour=end_t.hour, minute=end_t.minute, second=0, microsecond=0)
            if today_start <= now <= today_end:
                open_now = True
            elif now < today_start:
                next_open_label = f"วันนี้ {info_today.get('start')}"

    if not open_now and not next_open_label:
        for offset in range(1, 8):
            idx = (now.weekday() + offset) % 7
            key = weekday_keys[idx]
            info = hours.get(key, {}) if isinstance(hours, dict) else {}
            if info.get("open") and info.get("start"):
                label_day = "พรุ่งนี้" if offset == 1 else f"อีก {offset} วัน"
                next_open_label = f"{label_day} เวลา {info.get('start')}"
                break

    return {
        "open": open_now,
        "next_open": next_open_label,
        "current_time": now.strftime("%H:%M"),
        "timezone": tz.key,
    }


def _parse_order_item_details(note: str | None) -> Dict[str, str]:
    result = {"noodle": "", "extras": "", "other": ""}
    if not note:
        return result
    parts = [part.strip() for part in note.split("|") if part.strip()]
    extras_parts = []
    other_parts = []
    for part in parts:
        lowered = part.lower()
        if ":" in part:
            label, value = [seg.strip() for seg in part.split(":", 1)]
            if "เส้น" in label:
                result["noodle"] = value
            elif "เพิ่ม" in label or "พิเศษ" in label:
                extras_parts.append(value)
            else:
                other_parts.append(value)
        else:
            if "เพิ่ม" in lowered or "พิเศษ" in lowered:
                extras_parts.append(part)
            else:
                other_parts.append(part)
    if extras_parts:
        result["extras"] = ", ".join(extras_parts)
    if other_parts:
        result["other"] = " | ".join(other_parts)
    return result


def _save_menu_image(file_storage) -> str:
    if not file_storage or not file_storage.filename:
        raise ValueError("กรุณาเลือกรูปภาพที่ต้องการอัปโหลด")

    filename = secure_filename(file_storage.filename)
    if not filename:
        raise ValueError("ชื่อไฟล์ไม่ถูกต้อง")

    ext = Path(filename).suffix.lower().lstrip(".")
    allowed = current_app.config.get("MENU_IMAGE_ALLOWED_EXTENSIONS", set())
    if allowed and ext not in allowed:
        allowed_list = ", ".join(sorted(allowed))
        raise ValueError(f"รูปแบบไฟล์ไม่รองรับ (รองรับ: {allowed_list})")

    upload_dir = Path(current_app.config.get("MENU_IMAGE_UPLOAD_FOLDER", ""))
    upload_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    new_name = f"{timestamp}_{filename}"
    destination = upload_dir / new_name
    file_storage.save(destination)

    relative_folder = current_app.config.get("MENU_IMAGE_RELATIVE_FOLDER", "uploads/menu")
    return f"{relative_folder}/{new_name}"


def _remove_menu_image(relative_path: str | None) -> None:
    if not relative_path:
        return
    relative_folder = current_app.config.get("MENU_IMAGE_RELATIVE_FOLDER", "uploads/menu")
    if not relative_path.startswith(relative_folder):
        return
    static_root = Path(current_app.static_folder)
    file_path = static_root / relative_path
    try:
        if file_path.exists():
            file_path.unlink()
    except OSError:
        current_app.logger.warning("ไม่สามารถลบไฟล์รูป %s ได้", file_path)


def _normalize_selection_type(raw: str | None) -> str:
    value = (raw or "single").strip().lower()
    return value if value in {"single", "multiple"} else "single"


def _parse_line_restock_command(text: str) -> Tuple[str, float] | Tuple[None, None]:
    if not text:
        return None, None

    normalized = " ".join(text.strip().split())
    if not normalized:
        return None, None

    tokens = normalized.split(" ")
    command = tokens[0].lower()
    if command not in {"stock", "restock", "เติม", "เติมสต๊อก"}:
        return None, None
    if len(tokens) < 3:
        raise ValueError("รูปแบบไม่ถูกต้อง: ใช้เช่น stock ชื่อวัตถุดิบ 10")

    try:
        amount = round(float(tokens[-1]), 2)
    except (TypeError, ValueError):
        raise ValueError("จำนวนต้องเป็นตัวเลข เช่น 10 หรือ 2.5")

    if amount <= 0:
        raise ValueError("จำนวนต้องมากกว่า 0")

    ingredient_name = " ".join(tokens[1:-1]).strip()
    if not ingredient_name:
        raise ValueError("กรุณาระบุชื่อวัตถุดิบก่อนจำนวน")

    return ingredient_name, amount


def _restock_ingredient_from_line(name: str, amount: float, actor: str | None = None) -> Tuple[bool, str]:
    normalized = name.strip().lower()
    ingredient = db_session.scalar(
        select(Ingredient).where(func.lower(Ingredient.name) == normalized)
    )
    if not ingredient:
        return False, f"ไม่พบวัตถุดิบชื่อ '{name}' ในระบบ"

    note_parts = ["เติมสต๊อกจาก LINE"]
    if actor:
        note_parts.append(f"โดย {actor}")

    ingredient.quantity_on_hand = float(ingredient.quantity_on_hand or 0) + amount
    db_session.add(
        StockMovement(
            ingredient=ingredient,
            change=amount,
            movement_type=StockMovementTypeEnum.RESTOCK.value,
            note=" ".join(note_parts),
        )
    )

    affected_menu_items = [link.menu_item for link in ingredient.menu_links]
    _update_menu_item_availability(affected_menu_items)
    return True, f"เติม {ingredient.name} เพิ่ม {amount:.2f} {ingredient.unit} แล้ว (คงเหลือ {ingredient.quantity_on_hand:.2f})"


@main_blueprint.route("/line/webhook", methods=["POST"])
def line_webhook():
    channel_secret = current_app.config.get("LINE_CHANNEL_SECRET")
    channel_token = current_app.config.get("LINE_CHANNEL_ACCESS_TOKEN")

    if not channel_secret or not channel_token:
        current_app.logger.warning("Received LINE webhook but channel credentials are not configured")
        return jsonify({"message": "LINE webhook disabled"}), 200

    signature = request.headers.get("X-Line-Signature")
    if not signature:
        abort(400, description="Missing signature header")

    body = request.get_data(as_text=True)

    parser = WebhookParser(channel_secret)
    api = LineBotApi(channel_token)

    try:
        events = parser.parse(body, signature)
    except InvalidSignatureError:
        abort(400, description="Invalid signature")

    for event in events:
        response_text = None
        if isinstance(event, MessageEvent) and isinstance(event.message, TextMessage):
            response_text = _handle_line_text_event(event)

        if response_text:
            try:
                api.reply_message(event.reply_token, TextSendMessage(response_text))
            except LineBotApiError as exc:
                current_app.logger.warning("Failed to reply LINE message: %s", exc)

    return jsonify({"message": "ok"})


def _handle_line_text_event(event: MessageEvent) -> str | None:
    text = event.message.text or ""
    try:
        parsed = _parse_line_restock_command(text)
    except ValueError as exc:
        return str(exc)

    if not parsed or parsed == (None, None):
        return None

    ingredient_name, amount = parsed

    actor = getattr(event.source, "user_id", None)
    try:
        success, message = _restock_ingredient_from_line(ingredient_name, amount, actor)
        if success:
            db_session.commit()
        else:
            db_session.rollback()
        return message
    except Exception as exc:  # pragma: no cover - defensive
        db_session.rollback()
        current_app.logger.error("Failed to process LINE restock command: %s", exc, exc_info=True)
        return "ระบบไม่สามารถบันทึกสต๊อกได้ กรุณาลองใหม่หรือติดต่อผู้ดูแล"


@main_blueprint.route("/")
def home():
    user = session.get("user")
    if not user:
        return redirect(url_for("auth.login", role="admin", next=request.url))

    tables = list(
        db_session.scalars(select(DiningTable).order_by(DiningTable.name)).all()
    )
    return render_template("home.html", tables=tables)


@main_blueprint.route("/table/<string:table_code>")
def table_menu(table_code: str):
    table = db_session.scalar(
        select(DiningTable).where(DiningTable.code == table_code.upper())
    )
    if not table:
        abort(404, description="Table not found")

    if not table.access_token:
        table.access_token = secrets.token_hex(16)
        db_session.commit()

    token = request.args.get("token", "").strip()
    if table.access_token and token != table.access_token:
        abort(403, description="ไม่สามารถเข้าหน้าโต๊ะนี้ได้ (QR ไม่ถูกต้อง)")

    categories = db_session.scalars(
        select(MenuCategory).order_by(MenuCategory.position, MenuCategory.name)
    ).all()

    menu_configs: Dict[int, Dict[str, Any]] = {}
    for category in categories:
        for item in category.items:
            override_config = SPECIAL_MENU_CONFIG.get(item.name)
            groups_payload: List[Dict[str, Any]] = []
            for group in item.option_groups:
                options_payload = [
                    {
                        "id": option.id,
                        "name": option.name,
                        "price": float(option.price_delta or 0),
                        "position": option.position,
                    }
                    for option in group.options
                ]
                groups_payload.append(
                    {
                        "id": group.id,
                        "name": group.name,
                        "selection_type": group.selection_type,
                        "is_required": group.is_required,
                        "position": group.position,
                        "options": options_payload,
                    }
                )

            image_url = None
            image_alt = item.name
            if override_config:
                image_path = override_config.get("image")
                if image_path:
                    if isinstance(image_path, str) and image_path.startswith(("http://", "https://")):
                        image_url = image_path
                    else:
                        image_url = url_for("static", filename=image_path)
                image_alt = override_config.get("image_alt") or image_alt

            if not image_url and item.image_path:
                image_url = url_for("static", filename=item.image_path)

            special_payload = None
            if item.allow_special:
                special_payload = {
                    "label": "พิเศษ",
                    "price_delta": float(item.special_price_delta or 0),
                }

            menu_configs[item.id] = {
                "image": image_url,
                "image_alt": image_alt,
                "base_price": float(item.price),
                "groups": groups_payload,
                "special": special_payload,
            }

    store_status = _store_status()

    return render_template(
        "table_menu.html",
        table=table,
        categories=categories,
        menu_configs=menu_configs,
        store_status=store_status,
    )


@main_blueprint.route("/kitchen")
@login_required("kitchen")
def kitchen_dashboard():
    orders = _collect_orders(
        statuses=[
            OrderStatusEnum.PENDING.value,
            OrderStatusEnum.IN_PROGRESS.value,
            OrderStatusEnum.COMPLETED.value,
        ]
    )
    return render_template("kitchen.html", orders=orders)


@main_blueprint.route("/kitchen/orders-board")
@login_required("kitchen")
def kitchen_orders_board():
    noodle_orders = _collect_noodle_orders()
    return render_template(
        "kitchen_orders_table.html",
        orders=noodle_orders,
        status_labels=STATUS_LABELS,
    )


@main_blueprint.route("/api/kitchen/noodle-orders")
@login_required("kitchen")
def api_noodle_orders():
    payload = []
    for order, items in _collect_noodle_orders():
        payload.append(
            {
                "id": order.id,
                "table": order.table.name if order.table else "-",
                "status": order.status,
                "status_label": STATUS_LABELS.get(order.status, order.status),
                "created_at": order.created_at.isoformat(),
                "items": items,
            }
        )
    return jsonify({"orders": payload})


@main_blueprint.route("/api/menu")
def api_menu():
    result = []
    categories = db_session.scalars(
        select(MenuCategory).order_by(MenuCategory.position, MenuCategory.name)
    ).all()

    for category in categories:
        items_payload = [
            {
                "id": item.id,
                "name": item.name,
                "description": item.description,
                "price": float(item.price),
                "is_available": item.is_available,
            }
            for item in category.items
            if item.is_available
        ]
        if items_payload:
            result.append(
                {
                    "id": category.id,
                    "name": category.name,
                    "items": items_payload,
                }
            )

    return jsonify(result)


@main_blueprint.route("/api/game/config")
def api_game_config():
    target = _get_game_target()
    return jsonify({"target_squeezes": target})


@main_blueprint.route("/api/orders", methods=["POST"])
def api_create_order():
    payload = request.get_json(force=True)
    table_code = payload.get("table_code")
    items = payload.get("items", [])
    note = payload.get("note")

    if not table_code or not items:
        abort(400, description="Missing table code or order items")

    table = db_session.scalar(
        select(DiningTable).where(DiningTable.code == table_code.upper())
    )
    if not table:
        abort(404, description="Table not found")

    token = payload.get("token", "")
    if table.access_token and token != table.access_token:
        abort(403, description=" ไม่สามารถสั่งซื้อได้จากลิงก์นี้")

    status = _store_status()
    if status.get("open") is False:
        message = "ขณะนี้ร้านปิดอยู่"
        next_open = status.get("next_open")
        if next_open:
            message = f"ขณะนี้ร้านปิดอยู่ จะเปิดอีกครั้ง {next_open}"
        abort(403, description=message)

    # Simple rate limit per session toลดสแปม
    rate = session.get("order_rate") or {}
    now_ts = datetime.utcnow().timestamp()
    window_ts = rate.get("window_ts", 0)
    count = rate.get("count", 0)
    if now_ts - window_ts <= 60:
        if count >= 5:
            abort(429, description="ส่งคำสั่งซื้อมากเกินไป รอสักครู่แล้วลองใหม่")
        rate["count"] = count + 1
    else:
        rate = {"window_ts": now_ts, "count": 1}
    session["order_rate"] = rate

    order = Order(table=table, status=OrderStatusEnum.PENDING.value, note=note)
    db_session.add(order)

    selected_menu_pairs: List[Tuple[MenuItem, int]] = []

    for item_payload in items:
        menu_item_id = item_payload.get("menu_item_id")
        quantity = item_payload.get("quantity", 1)
        item_note = item_payload.get("note")
        unit_price_raw = item_payload.get("unit_price")

        if not menu_item_id or quantity <= 0:
            abort(400, description="Invalid order item data")

        menu_item = db_session.get(MenuItem, menu_item_id)
        if not menu_item or not menu_item.is_available:
            abort(400, description="Menu item unavailable")

        if unit_price_raw is not None:
            try:
                unit_price = round(float(unit_price_raw), 2)
            except (TypeError, ValueError):
                abort(400, description="Invalid unit price")
            if unit_price <= 0:
                abort(400, description="Invalid unit price")
        else:
            unit_price = float(menu_item.price)

        selected_menu_pairs.append((menu_item, quantity))

        order_item = OrderItem(
            order=order,
            menu_item=menu_item,
            quantity=quantity,
            note=item_note,
            unit_price=unit_price,
        )
        order.items.append(order_item)

    usage_totals, affected_menu_items = _calculate_inventory_usage(selected_menu_pairs)
    _reserve_stock_for_order(order, usage_totals, affected_menu_items)

    db_session.commit()
    db_session.refresh(order)

    notifications.notify_new_order(order)

    formatted = _order_to_dict(order)
    return jsonify(formatted), 201


@main_blueprint.route("/api/orders/<int:order_id>")
def api_get_order(order_id: int):
    order = db_session.get(Order, order_id)
    if not order:
        abort(404, description="Order not found")
    return jsonify(_order_to_dict(order))


@main_blueprint.route("/api/orders/pending")
def api_pending_orders():
    orders = _collect_orders(
        statuses=[
            OrderStatusEnum.PENDING.value,
            OrderStatusEnum.IN_PROGRESS.value,
            OrderStatusEnum.COMPLETED.value,
        ]
    )
    return jsonify(orders)


@main_blueprint.route("/api/orders/<int:order_id>/status", methods=["POST"])
def api_update_order_status(order_id: int):
    payload = request.get_json(force=True)
    new_status = payload.get("status")
    valid_statuses = {status.value for status in OrderStatusEnum}

    if new_status not in valid_statuses:
        abort(400, description="Invalid status")

    order = db_session.get(Order, order_id)
    if not order:
        abort(404, description="Order not found")

    order.status = new_status
    if new_status == OrderStatusEnum.PAID.value:
        if not order.is_paid:
            payment = Payment(
                order=order,
                amount=order.grand_total,
                method=PaymentMethodEnum.PROMPTPAY.value,
                reference="PromptPay QR",
                note="Auto capture from QR confirmation",
            )
            db_session.add(payment)
        if not order.paid_at:
            order.paid_at = datetime.utcnow()
        _ensure_invoice(order)
    db_session.commit()

    return jsonify(_order_to_dict(order))


@main_blueprint.route("/api/tables/<string:table_code>/last-order")
def api_table_last_order(table_code: str):
    table = db_session.scalar(
        select(DiningTable).where(DiningTable.code == table_code.upper())
    )
    if not table:
        abort(404, description="Table not found")

    last_order = (
        db_session.query(Order)
        .filter(
            Order.table_id == table.id,
            Order.status != OrderStatusEnum.PAID.value,
        )
        .order_by(Order.created_at.desc())
        .first()
    )
    if not last_order:
        return jsonify({"order": None})
    return jsonify({"order": _order_to_dict(last_order)})


@main_blueprint.route("/api/tables/<string:table_code>/orders")
def api_table_orders(table_code: str):
    table = db_session.scalar(
        select(DiningTable).where(DiningTable.code == table_code.upper())
    )
    if not table:
        abort(404, description="Table not found")

    orders = (
        db_session.query(Order)
        .filter(
            Order.table_id == table.id,
            Order.status != OrderStatusEnum.PAID.value,
        )
        .order_by(Order.created_at.asc())
        .all()
    )
    return jsonify({"orders": [_order_to_dict(order) for order in orders]})


@main_blueprint.route("/order/<int:order_id>")
def order_status_page(order_id: int):
    order = db_session.get(Order, order_id)
    if not order:
        abort(404, description="Order not found")
    return render_template("order_status.html", order=_order_to_dict(order))


@main_blueprint.route("/admin")
@login_required("admin")
def admin_dashboard():
    _backfill_invoices()
    total_orders = db_session.query(func.count(Order.id)).scalar() or 0
    pending = (
        db_session.query(func.count(Order.id))
        .filter(Order.status == OrderStatusEnum.PENDING.value)
        .scalar()
        or 0
    )
    in_progress = (
        db_session.query(func.count(Order.id))
        .filter(Order.status == OrderStatusEnum.IN_PROGRESS.value)
        .scalar()
        or 0
    )
    completed = (
        db_session.query(func.count(Order.id))
        .filter(Order.status == OrderStatusEnum.COMPLETED.value)
        .scalar()
        or 0
    )
    paid = (
        db_session.query(func.count(Order.id))
        .filter(Order.status == OrderStatusEnum.PAID.value)
        .scalar()
        or 0
    )
    invoice_count = db_session.query(func.count(Invoice.id)).scalar() or 0

    total_sales = (
        db_session.query(
            func.coalesce(
                func.sum(
                    OrderItem.quantity * func.coalesce(OrderItem.unit_price, MenuItem.price)
                ),
                0,
            )
        )
        .join(MenuItem, MenuItem.id == OrderItem.menu_item_id)
        .join(Order, Order.id == OrderItem.order_id)
        .filter(Order.status == OrderStatusEnum.PAID.value)
        .scalar()
        or 0
    )

    top_items = (
        db_session.query(
            MenuItem.name,
            func.sum(OrderItem.quantity).label("qty"),
        )
        .join(MenuItem, MenuItem.id == OrderItem.menu_item_id)
        .join(Order, Order.id == OrderItem.order_id)
        .filter(Order.status == OrderStatusEnum.PAID.value)
        .group_by(MenuItem.id, MenuItem.name)
        .order_by(func.sum(OrderItem.quantity).desc())
        .limit(5)
        .all()
    )

    recent_orders = (
        db_session.query(Order)
        .order_by(Order.created_at.desc())
        .limit(10)
        .all()
    )

    promptpay_exists = Path("static/promptpay.png").exists()
    recent_invoices = (
        db_session.query(Invoice)
        .join(Order)
        .order_by(Invoice.created_at.desc())
        .limit(5)
        .all()
    )

    return render_template(
        "admin/dashboard.html",
        stats={
            "total_orders": total_orders,
            "pending": pending,
            "in_progress": in_progress,
            "completed": completed,
            "paid": paid,
            "total_sales": float(total_sales),
            "invoice_count": invoice_count,
        },
        top_items=top_items,
        recent_orders=[_order_to_dict(order) for order in recent_orders],
        promptpay_exists=promptpay_exists,
        recent_invoices=recent_invoices,
    )


@main_blueprint.route("/admin/orders/<int:order_id>")
@login_required("admin")
def admin_order_detail(order_id: int):
    order = db_session.get(Order, order_id)
    if not order:
        abort(404, description="Order not found")
    if order.status == OrderStatusEnum.PAID.value:
        _backfill_invoices(order_ids=[order.id])
    return render_template(
        "admin/order_detail.html",
        order=order,
        order_data=_order_to_dict(order),
        payment_methods=list(PaymentMethodEnum),
        payment_labels=PAYMENT_METHOD_LABELS,
    )


@main_blueprint.route("/admin/orders/<int:order_id>/update", methods=["POST"])
@login_required("admin")
def admin_update_order(order_id: int):
    order = db_session.get(Order, order_id)
    if not order:
        abort(404, description="Order not found")

    def parse_amount(field_name: str) -> float:
        raw_value = request.form.get(field_name, "").strip()
        existing = getattr(order, field_name, 0)  # stored as Decimal/float
        try:
            existing_value = max(0.0, float(existing))
        except (TypeError, ValueError):
            existing_value = 0.0
        if raw_value == "":
            return existing_value
        try:
            return max(0.0, float(raw_value))
        except (TypeError, ValueError):
            return existing_value

    discount = parse_amount("discount_amount")
    service_charge = parse_amount("service_charge")
    tax_rate = parse_amount("tax_rate")
    note = request.form.get("note", order.note or "").strip()

    order.discount_amount = discount
    order.service_charge = service_charge
    order.tax_rate = tax_rate
    order.note = note or None

    db_session.commit()
    flash("อัปเดตข้อมูลออเดอร์เรียบร้อยแล้ว", "success")
    return redirect(url_for("main.admin_order_detail", order_id=order.id))


@main_blueprint.route("/admin/orders/<int:order_id>/pay", methods=["POST"])
@login_required("admin")
def admin_pay_order(order_id: int):
    order = db_session.get(Order, order_id)
    if not order:
        abort(404, description="Order not found")

    amount_raw = request.form.get("amount", "").strip()
    method = request.form.get("method", PaymentMethodEnum.CASH.value)
    reference = request.form.get("reference", "").strip() or None
    note = request.form.get("payment_note", "").strip() or None

    try:
        amount = round(float(amount_raw), 2)
    except (TypeError, ValueError):
        flash("จำนวนเงินไม่ถูกต้อง", "error")
        return redirect(url_for("main.admin_order_detail", order_id=order.id))

    if amount <= 0:
        flash("จำนวนเงินต้องมากกว่า 0", "error")
        return redirect(url_for("main.admin_order_detail", order_id=order.id))

    if method not in PAYMENT_METHOD_LABELS:
        method = PaymentMethodEnum.CASH.value

    balance_due = order.balance_due
    if balance_due > 0 and amount > balance_due + 0.01:
        flash(
            f"จำนวนเงินมากกว่ายอดที่ต้องชำระ ({balance_due:.2f} บาท)",
            "error",
        )
        return redirect(url_for("main.admin_order_detail", order_id=order.id))

    payment = Payment(
        order=order,
        amount=amount,
        method=method,
        reference=reference,
        note=note,
    )
    db_session.add(payment)
    db_session.flush()

    if order.balance_due <= 0:
        order.status = OrderStatusEnum.PAID.value
        order.paid_at = payment.paid_at
        _ensure_invoice(order)

    db_session.commit()
    flash("บันทึกการชำระเงินเรียบร้อย", "success")
    return redirect(url_for("main.admin_order_detail", order_id=order.id))


@main_blueprint.route("/admin/orders/<int:order_id>/receipt")
@login_required("admin")
def admin_order_receipt(order_id: int):
    order = db_session.get(Order, order_id)
    if not order:
        abort(404, description="Order not found")
    return render_template(
        "admin/receipt.html",
        order=order,
        order_data=_order_to_dict(order),
        payment_labels=PAYMENT_METHOD_LABELS,
    )


@main_blueprint.route("/admin/billing/promptpay", methods=["POST"])
@login_required("adminpp")
def admin_update_promptpay():
    target = request.form.get("promptpay_target", "").strip()
    next_url = request.form.get("next") or url_for("main.admin_billing_overview")

    if target:
        try:
            normalize_target(target)
        except ValueError:
            flash("หมายเลข PromptPay ไม่ถูกต้อง", "error")
            return redirect(next_url)

    setting = (
        db_session.query(Setting)
        .filter(Setting.key == "promptpay_target")
        .one_or_none()
    )

    if target:
        if setting:
            setting.value = target
        else:
            db_session.add(Setting(key="promptpay_target", value=target))
        message = "บันทึกหมายเลข PromptPay เรียบร้อย"
    else:
        if setting:
            db_session.delete(setting)
        message = "ล้างการตั้งค่า PromptPay เรียบร้อย"

    db_session.commit()
    flash(message, "success")
    return redirect(next_url)


@main_blueprint.route("/admin/billing")
@login_required("admin")
def admin_billing_overview():
    tables = db_session.scalars(
        select(DiningTable).order_by(DiningTable.name.asc())
    ).all()

    summaries: List[Dict[str, Any]] = []
    for table in tables:
        pending_orders = (
            db_session.query(Order)
            .filter(
                Order.table_id == table.id,
                Order.status != OrderStatusEnum.PAID.value,
            )
            .order_by(Order.created_at.asc())
            .all()
        )

        unpaid_orders = []
        total_due = 0.0
        for order in pending_orders:
            due = max(order.balance_due, 0.0)
            if due <= 0:
                continue
            unpaid_orders.append(order)
            total_due += due

        summaries.append(
            {
                "table": table,
                "order_count": len(unpaid_orders),
                "total_due": round(total_due, 2),
            }
        )

    raw_target, normalized_target = _promptpay_config()
    user = session.get("user") or {}
    can_manage_promptpay = "adminpp" in user.get("roles", [])
    return render_template(
        "admin/billing.html",
        tables=summaries,
        promptpay_target=raw_target,
        promptpay_ready=bool(normalized_target),
        can_manage_promptpay=can_manage_promptpay,
    )


@main_blueprint.route("/admin/game-settings", methods=["GET", "POST"])
@login_required("adminpp")
def admin_game_settings():
    current_target = _get_game_target()
    if request.method == "POST":
        raw_target = request.form.get("target", "").strip()
        try:
            target = int(raw_target)
        except (TypeError, ValueError):
            flash("กรุณาระบุจำนวนครั้งเป็นตัวเลข", "error")
            return redirect(url_for("main.admin_game_settings"))
        if target <= 0:
            flash("จำนวนครั้งต้องมากกว่า 0", "error")
            return redirect(url_for("main.admin_game_settings"))

        setting = db_session.query(Setting).filter(Setting.key == "game_target").one_or_none()
        if setting:
            setting.value = str(target)
        else:
            db_session.add(Setting(key="game_target", value=str(target)))
        db_session.commit()
        flash("บันทึกเป้าหมายเกมเรียบร้อย", "success")
        return redirect(url_for("main.admin_game_settings"))

    return render_template("admin/game_settings.html", target=current_target)


@main_blueprint.route("/admin/store-hours", methods=["GET", "POST"])
@login_required("adminpp")
def admin_store_hours():
    days = [
        ("monday", "วันจันทร์"),
        ("tuesday", "วันอังคาร"),
        ("wednesday", "วันพุธ"),
        ("thursday", "วันพฤหัสบดี"),
        ("friday", "วันศุกร์"),
        ("saturday", "วันเสาร์"),
        ("sunday", "วันอาทิตย์"),
    ]
    current_hours = _get_store_hours()

    if request.method == "POST":
        new_hours: Dict[str, Dict[str, str | bool]] = {}
        for key, _label in days:
            is_open = request.form.get(f"open_{key}") == "on"
            open_time = request.form.get(f"start_{key}", "").strip()
            close_time = request.form.get(f"end_{key}", "").strip()

            if is_open:
                if not open_time or not close_time:
                    flash("กรุณาระบุเวลาเปิด-ปิดให้ครบทุกวันที่เปิด", "error")
                    return redirect(url_for("main.admin_store_hours"))
                new_hours[key] = {
                    "open": True,
                    "start": open_time,
                    "end": close_time,
                }
            else:
                new_hours[key] = {"open": False, "start": "", "end": ""}

        _save_store_hours(new_hours)
        flash("บันทึกเวลาเปิด-ปิดร้านเรียบร้อย", "success")
        return redirect(url_for("main.admin_store_hours"))

    return render_template("admin/store_hours.html", days=days, hours=current_hours)


@main_blueprint.route("/admin/auth-settings", methods=["GET", "POST"])
@login_required("adminpp")
def admin_auth_settings():
    current_admin = _get_auth_password("admin")
    current_kitchen = _get_auth_password("kitchen")

    if request.method == "POST":
        target = request.form.get("target")
        new_password = request.form.get("password", "").strip()
        confirm_password = request.form.get("password_confirm", "").strip()

        if target not in {"admin", "kitchen"}:
            flash("ไม่พบประเภทบัญชีที่ต้องการเปลี่ยนรหัส", "error")
            return redirect(url_for("main.admin_auth_settings"))
        if not new_password:
            flash("กรุณาระบุรหัสผ่านใหม่", "error")
            return redirect(url_for("main.admin_auth_settings"))
        if new_password != confirm_password:
            flash("รหัสผ่านยืนยันไม่ตรงกัน", "error")
            return redirect(url_for("main.admin_auth_settings"))

        _set_auth_password(target, new_password)
        flash("บันทึกรหัสผ่านใหม่เรียบร้อย", "success")
        return redirect(url_for("main.admin_auth_settings"))

    return render_template(
        "admin/auth_settings.html",
        current_admin=current_admin,
        current_kitchen=current_kitchen,
    )


@main_blueprint.route("/admin/billing/<string:table_code>")
@login_required("admin")
def admin_billing_table_view(table_code: str):
    table = db_session.scalar(
        select(DiningTable).where(DiningTable.code == table_code.upper())
    )
    if not table:
        abort(404, description="Table not found")

    orders = (
        db_session.query(Order)
        .filter(
            Order.table_id == table.id,
            Order.status != OrderStatusEnum.PAID.value,
        )
        .order_by(Order.created_at.asc())
        .all()
    )
    raw_target, normalized_target = _promptpay_config()
    table_url = None
    if table.access_token:
        table_url = _build_table_menu_url(table.code)
        table_url = f"{table_url}?token={table.access_token}"
    return render_template(
        "admin/billing_table.html",
        table=table,
        orders=orders,
        status_labels=STATUS_LABELS,
        promptpay_target=raw_target,
        promptpay_ready=bool(normalized_target),
        store_status=_store_status(),
        table_order_url=table_url,
    )


@main_blueprint.route("/admin/billing/<string:table_code>/orders/<int:order_id>/cancel", methods=["POST"])
@login_required("admin")
def admin_cancel_order(table_code: str, order_id: int):
    table = db_session.scalar(
        select(DiningTable).where(DiningTable.code == table_code.upper())
    )
    if not table:
        abort(404, description="Table not found")

    order = db_session.get(Order, order_id)
    if not order or order.table_id != table.id:
        abort(404, description="Order not found")

    if order.status == OrderStatusEnum.PAID.value:
        flash("ไม่สามารถยกเลิกออเดอร์ที่ชำระเงินแล้ว", "error")
        return redirect(url_for("main.admin_billing_table_view", table_code=table.code))

    _release_stock_for_order(order)
    db_session.delete(order)
    db_session.commit()
    flash(f"ยกเลิกออเดอร์ #{order.id} เรียบร้อย", "success")
    return redirect(url_for("main.admin_billing_table_view", table_code=table.code))


@main_blueprint.route("/admin/billing/qr", methods=["POST"])
@login_required("admin")
def admin_generate_billing_qr():
    payload = request.get_json(force=True, silent=False)
    table_code = (payload.get("table_code") or "").strip().upper()
    raw_ids = payload.get("order_ids", [])

    try:
        order_ids = [int(value) for value in raw_ids]
    except (TypeError, ValueError):
        return jsonify({"message": "ข้อมูลรายการไม่ถูกต้อง"}), 400

    if not table_code or not order_ids:
        return jsonify({"message": "กรุณาเลือกรายการค้างชำระ"}), 400

    table = db_session.scalar(
        select(DiningTable).where(DiningTable.code == table_code)
    )
    if not table:
        return jsonify({"message": "ไม่พบโต๊ะนี้ในระบบ"}), 404

    orders = (
        db_session.query(Order)
        .filter(
            Order.table_id == table.id,
            Order.id.in_(order_ids),
        )
        .order_by(Order.created_at.asc())
        .all()
    )
    found_ids = {order.id for order in orders}
    expected_ids = set(order_ids)
    if expected_ids - found_ids:
        return jsonify({"message": "รายการไม่ตรงกับโต๊ะที่เลือก"}), 400

    unpaid_orders: List[Order] = []
    total_due = 0.0
    for order in orders:
        due = max(order.balance_due, 0.0)
        if due <= 0:
            continue
        unpaid_orders.append(order)
        total_due += due

    gross_amount = round(total_due, 2)
    if gross_amount <= 0:
        return jsonify({"message": "รายการที่เลือกไม่มีค้างชำระ"}), 400

    discount_raw = payload.get("discount_amount", 0)
    try:
        discount_amount = round(float(discount_raw), 2)
    except (TypeError, ValueError):
        return jsonify({"message": "รูปแบบส่วนลดไม่ถูกต้อง"}), 400
    if discount_amount < 0:
        discount_amount = 0.0
    if discount_amount > gross_amount:
        discount_amount = gross_amount

    net_amount = round(gross_amount - discount_amount, 2)
    if net_amount <= 0:
        return jsonify({"message": "ยอดสุทธิหลังหักส่วนลดต้องมากกว่า 0"}), 400

    raw_target, normalized_target = _promptpay_config()
    if not normalized_target:
        return jsonify({"message": "ยังไม่ได้ตั้งค่า PromptPay สำหรับร้าน"}), 400

    try:
        payload_value = build_promptpay_payload(normalized_target, net_amount)
        qr_image = generate_qr_base64(payload_value)
    except Exception:
        current_app.logger.exception("Failed to generate PromptPay QR for table %s", table.code)
        return jsonify({"message": "ระบบไม่สามารถสร้าง QR ได้ กรุณาลองใหม่อีกครั้ง"}), 500

    return jsonify(
        {
            "amount": net_amount,
            "gross_amount": gross_amount,
            "discount_applied": discount_amount,
            "formatted_amount": f"{net_amount:.2f}",
            "orders": [order.id for order in unpaid_orders],
            "payload": payload_value,
            "qr_image": qr_image,
            "target": raw_target,
        }
    )


@main_blueprint.route("/admin/billing/<string:table_code>/settle", methods=["POST"])
@login_required("admin")
def admin_settle_billing_orders(table_code: str):
    table = db_session.scalar(
        select(DiningTable).where(DiningTable.code == table_code.upper())
    )
    if not table:
        abort(404, description="Table not found")

    order_ids_raw = request.form.get("order_ids", "").strip()
    try:
        order_ids = [int(value) for value in order_ids_raw.split(",") if value]
    except ValueError:
        order_ids = []

    if not order_ids:
        flash("กรุณาเลือกรายการที่ต้องการปิดบิล", "error")
        return redirect(
            url_for("main.admin_billing_table_view", table_code=table.code)
        )

    reference = request.form.get("reference", "").strip() or None

    orders = (
        db_session.query(Order)
        .filter(
            Order.table_id == table.id,
            Order.id.in_(order_ids),
        )
        .order_by(Order.created_at.asc())
        .all()
    )
    found_ids = {order.id for order in orders}
    expected_ids = set(order_ids)
    if expected_ids - found_ids:
        flash("พบรายการที่ไม่ตรงกับโต๊ะนี้", "error")
        return redirect(
            url_for("main.admin_billing_table_view", table_code=table.code)
        )

    total_recorded = 0.0
    for order in orders:
        due = round(max(order.balance_due, 0.0), 2)
        if due <= 0:
            continue
        payment = Payment(
            order=order,
            amount=due,
            method=PaymentMethodEnum.PROMPTPAY.value,
            reference=reference,
            note=f"ชำระผ่าน PromptPay โต๊ะ {table.code}",
        )
        db_session.add(payment)
        db_session.flush()
        if order.balance_due <= 0:
            order.status = OrderStatusEnum.PAID.value
            order.paid_at = payment.paid_at
        total_recorded += due

    if total_recorded <= 0:
        flash("ไม่มียอดคงค้างสำหรับรายการที่เลือก", "warning")
        db_session.rollback()
        return redirect(
            url_for("main.admin_billing_table_view", table_code=table.code)
        )

    db_session.commit()
    flash(f"บันทึกการชำระเงินรวม {total_recorded:.2f} บาทแล้ว", "success")
    return redirect(
        url_for("main.admin_billing_table_view", table_code=table.code)
    )


@main_blueprint.route("/admin/download-promptpay")
@login_required("admin")
def download_promptpay_qr():
    qr_path = Path("static/promptpay.png")
    if not qr_path.exists():
        return redirect(
            url_for(
                "main.admin_dashboard",
                error="ยังไม่พบไฟล์ promptpay.png กรุณาใช้สคริปต์ generate_promptpay_qr.py ก่อน",
            )
        )
    return send_file(qr_path, mimetype="image/png", as_attachment=True)


@main_blueprint.route("/admin/invoices")
@login_required("admin")
def admin_invoices():
    _backfill_invoices()
    invoices = (
        db_session.query(Invoice)
        .join(Order)
        .order_by(Invoice.created_at.desc())
        .all()
    )
    return render_template("admin/invoices.html", invoices=invoices)


@main_blueprint.route("/admin/invoices/<int:invoice_id>/download")
@login_required("admin")
def download_invoice(invoice_id: int):
    invoice = db_session.get(Invoice, invoice_id)
    if not invoice:
        abort(404, description="Invoice not found")

    image_stream = _render_invoice_image(invoice)
    return send_file(
        image_stream,
        mimetype="image/png",
        as_attachment=True,
        download_name=f"invoice-{invoice.id}.png",
    )


@main_blueprint.route("/admin/invoices.csv")
@login_required("admin")
def export_invoices_csv():
    _backfill_invoices()
    invoices = (
        db_session.query(Invoice)
        .join(Order)
        .order_by(Invoice.created_at.desc())
        .all()
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "invoice_id",
            "order_id",
            "table",
            "net_amount",
            "tax_amount",
            "total_amount",
            "paid_at",
            "created_at",
        ]
    )
    for invoice in invoices:
        order = invoice.order
        writer.writerow(
            [
                invoice.id,
                order.id,
                f"{order.table.name} ({order.table.code})",
                f"{float(invoice.net_amount):.2f}",
                f"{float(invoice.tax_amount):.2f}",
                f"{float(invoice.total_amount):.2f}",
                order.paid_at.strftime("%Y-%m-%d %H:%M:%S") if order.paid_at else "",
                invoice.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            ]
        )

    csv_bytes = output.getvalue().encode("utf-8-sig")
    output.close()

    return send_file(
        io.BytesIO(csv_bytes),
        mimetype="text/csv",
        as_attachment=True,
        download_name="invoices.csv",
    )


@main_blueprint.route("/instant-game/")
@main_blueprint.route("/instant-game/<path:path>")
def instant_game(path: str = "index.html"):
    instant_dir = BASE_DIR / "instant_game"
    return send_from_directory(instant_dir, path)


@main_blueprint.route("/admin/menu")
@login_required("admin")
def admin_manage_menu():
    categories = db_session.scalars(
        select(MenuCategory).order_by(MenuCategory.position, MenuCategory.name)
    ).all()
    ingredients = db_session.scalars(
        select(Ingredient).order_by(Ingredient.name.asc())
    ).all()
    return render_template(
        "admin/menu.html",
        categories=categories,
        ingredients=ingredients,
    )


@main_blueprint.route("/admin/menu/categories", methods=["POST"])
@login_required("admin")
def admin_create_category():
    name = request.form.get("name", "").strip()
    position_raw = request.form.get("position", "").strip()

    if not name:
        flash("กรุณากรอกชื่อหมวดหมู่", "error")
        return redirect(url_for("main.admin_manage_menu"))

    try:
        position = int(position_raw) if position_raw else 0
    except ValueError:
        position = 0

    db_session.add(MenuCategory(name=name, position=position))
    db_session.commit()
    flash("เพิ่มหมวดหมู่เมนูเรียบร้อย", "success")
    return redirect(url_for("main.admin_manage_menu"))


@main_blueprint.route("/admin/menu/items", methods=["POST"])
@login_required("admin")
def admin_create_menu_item():
    name = request.form.get("name", "").strip()
    price_raw = request.form.get("price", "").strip()
    category_id_raw = request.form.get("category_id", "").strip()
    description = request.form.get("description", "").strip() or None
    position_raw = request.form.get("position", "").strip()
    image_file = request.files.get("image")
    allow_special = request.form.get("allow_special") == "on"
    special_price_raw = request.form.get("special_price_delta", "").strip()

    if not name or not price_raw or not category_id_raw:
        flash("กรุณากรอกข้อมูลเมนูให้ครบถ้วน", "error")
        return redirect(url_for("main.admin_manage_menu"))

    try:
        price = round(float(price_raw), 2)
    except (TypeError, ValueError):
        flash("ราคาต้องเป็นตัวเลข", "error")
        return redirect(url_for("main.admin_manage_menu"))

    image_path = None
    if image_file and image_file.filename:
        try:
            image_path = _save_menu_image(image_file)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("main.admin_manage_menu"))

    try:
        category_id = int(category_id_raw)
    except (TypeError, ValueError):
        flash("หมวดหมู่ไม่ถูกต้อง", "error")
        return redirect(url_for("main.admin_manage_menu"))

    try:
        position = int(position_raw) if position_raw else 0
    except ValueError:
        position = 0

    special_price = 0.0
    if special_price_raw:
        try:
            special_price = round(float(special_price_raw), 2)
        except (TypeError, ValueError):
            flash("ราคาพิเศษต้องเป็นตัวเลข", "error")
            return redirect(url_for("main.admin_manage_menu"))
        if special_price < 0:
            flash("ราคาพิเศษต้องไม่ติดลบ", "error")
            return redirect(url_for("main.admin_manage_menu"))
    if not allow_special:
        special_price = 0.0

    category = db_session.get(MenuCategory, category_id)
    if not category:
        flash("ไม่พบหมวดหมู่ที่เลือก", "error")
        return redirect(url_for("main.admin_manage_menu"))

    menu_item = MenuItem(
        name=name,
        description=description,
        price=price,
        category=category,
        is_available=True,
        position=position,
        image_path=image_path,
        allow_special=allow_special,
        special_price_delta=special_price,
    )
    db_session.add(menu_item)
    db_session.commit()
    flash("เพิ่มเมนูใหม่เรียบร้อย", "success")
    return redirect(url_for("main.admin_manage_menu"))


@main_blueprint.route("/admin/menu/items/<int:item_id>/update", methods=["POST"])
@login_required("admin")
def admin_update_menu_item(item_id: int):
    menu_item = db_session.get(MenuItem, item_id)
    if not menu_item:
        abort(404, description="Menu item not found")

    name = request.form.get("name", "").strip()
    description = request.form.get("description", menu_item.description or "").strip() or None
    price_raw = request.form.get("price", "").strip()
    category_id_raw = request.form.get("category_id", "").strip()
    position_raw = request.form.get("position", "").strip()
    is_available = request.form.get("is_available") == "on"
    remove_image = request.form.get("remove_image") == "on"
    image_file = request.files.get("image")
    allow_special = request.form.get("allow_special") == "on"
    special_price_raw = request.form.get("special_price_delta", "").strip()

    if not name:
        flash("กรุณากรอกชื่อเมนู", "error")
        return redirect(url_for("main.admin_manage_menu"))

    try:
        price = round(float(price_raw), 2) if price_raw else float(menu_item.price)
    except (TypeError, ValueError):
        flash("ราคาต้องเป็นตัวเลข", "error")
        return redirect(url_for("main.admin_manage_menu"))

    category = menu_item.category
    if category_id_raw:
        try:
            category_candidate = db_session.get(MenuCategory, int(category_id_raw))
            if category_candidate:
                category = category_candidate
        except (TypeError, ValueError):
            pass

    position = menu_item.position
    if position_raw:
        try:
            position = int(position_raw)
        except ValueError:
            flash("ลำดับต้องเป็นตัวเลข", "error")
            return redirect(url_for("main.admin_manage_menu"))

    new_image_path = None
    if image_file and image_file.filename:
        try:
            new_image_path = _save_menu_image(image_file)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("main.admin_manage_menu"))

    menu_item.name = name
    menu_item.description = description
    menu_item.price = price
    menu_item.category = category
    menu_item.position = position
    menu_item.is_available = is_available

    if new_image_path:
        _remove_menu_image(menu_item.image_path)
        menu_item.image_path = new_image_path
    elif remove_image and menu_item.image_path:
        _remove_menu_image(menu_item.image_path)
        menu_item.image_path = None

    special_price = 0.0
    if special_price_raw:
        try:
            special_price = round(float(special_price_raw), 2)
        except (TypeError, ValueError):
            flash("ราคาพิเศษต้องเป็นตัวเลข", "error")
            return redirect(url_for("main.admin_manage_menu"))
        if special_price < 0:
            flash("ราคาพิเศษต้องไม่ติดลบ", "error")
            return redirect(url_for("main.admin_manage_menu"))
    if allow_special:
        menu_item.special_price_delta = special_price
        menu_item.allow_special = True
    else:
        menu_item.allow_special = False
        menu_item.special_price_delta = 0

    _update_menu_item_availability([menu_item])
    db_session.commit()
    flash("บันทึกการแก้ไขเมนูเรียบร้อย", "success")
    return redirect(url_for("main.admin_manage_menu"))


@main_blueprint.route("/admin/menu/items/<int:item_id>/ingredients", methods=["POST"])
@login_required("admin")
def admin_add_menu_item_ingredient(item_id: int):
    menu_item = db_session.get(MenuItem, item_id)
    if not menu_item:
        abort(404, description="Menu item not found")

    ingredient_id_raw = request.form.get("ingredient_id", "").strip()
    quantity_raw = request.form.get("quantity", "").strip()

    if not ingredient_id_raw or not quantity_raw:
        flash("กรุณาเลือกวัตถุดิบและจำนวนที่ใช้", "error")
        return redirect(url_for("main.admin_manage_menu"))

    try:
        ingredient_id = int(ingredient_id_raw)
        quantity = max(0.0, float(quantity_raw))
    except (TypeError, ValueError):
        flash("ข้อมูลวัตถุดิบไม่ถูกต้อง", "error")
        return redirect(url_for("main.admin_manage_menu"))

    ingredient = db_session.get(Ingredient, ingredient_id)
    if not ingredient:
        flash("ไม่พบวัตถุดิบที่เลือก", "error")
        return redirect(url_for("main.admin_manage_menu"))

    link = (
        db_session.query(MenuItemIngredient)
        .filter_by(menu_item_id=menu_item.id, ingredient_id=ingredient.id)
        .first()
    )

    if link:
        link.quantity = quantity
        message = "อัปเดตจำนวนวัตถุดิบเรียบร้อย"
    else:
        link = MenuItemIngredient(
            menu_item=menu_item,
            ingredient=ingredient,
            quantity=quantity,
        )
        db_session.add(link)
        message = "เพิ่มวัตถุดิบให้เมนูเรียบร้อย"

    _update_menu_item_availability([menu_item])
    db_session.commit()
    flash(message, "success")
    return redirect(url_for("main.admin_manage_menu"))


@main_blueprint.route(
    "/admin/menu/items/<int:item_id>/ingredients/<int:link_id>/delete", methods=["POST"]
)
@login_required("admin")
def admin_remove_menu_item_ingredient(item_id: int, link_id: int):
    menu_item = db_session.get(MenuItem, item_id)
    if not menu_item:
        abort(404, description="Menu item not found")

    link = db_session.get(MenuItemIngredient, link_id)
    if not link or link.menu_item_id != menu_item.id:
        flash("ไม่พบความสัมพันธ์วัตถุดิบ", "error")
        return redirect(url_for("main.admin_manage_menu"))

    db_session.delete(link)
    db_session.flush()
    _update_menu_item_availability([menu_item])
    db_session.commit()
    flash("ลบวัตถุดิบออกจากเมนูเรียบร้อย", "success")
    return redirect(url_for("main.admin_manage_menu"))


@main_blueprint.route(
    "/admin/menu/items/<int:item_id>/option-groups",
    methods=["POST"],
)
@login_required("admin")
def admin_create_option_group(item_id: int):
    menu_item = db_session.get(MenuItem, item_id)
    if not menu_item:
        abort(404, description="Menu item not found")

    name = request.form.get("name", "").strip()
    selection_type = _normalize_selection_type(request.form.get("selection_type"))
    is_required = request.form.get("is_required") == "on"
    position_raw = request.form.get("position", "").strip()

    if not name:
        flash("กรุณาระบุชื่อกลุ่มตัวเลือก", "error")
        return redirect(url_for("main.admin_manage_menu"))

    try:
        position = int(position_raw) if position_raw else 0
    except ValueError:
        flash("ลำดับต้องเป็นตัวเลข", "error")
        return redirect(url_for("main.admin_manage_menu"))

    group = MenuOptionGroup(
        menu_item=menu_item,
        name=name,
        selection_type=selection_type,
        is_required=is_required,
        position=position,
    )
    db_session.add(group)
    db_session.commit()
    flash("เพิ่มกลุ่มตัวเลือกเรียบร้อย", "success")
    return redirect(url_for("main.admin_manage_menu"))


@main_blueprint.route(
    "/admin/menu/items/<int:item_id>/option-groups/<int:group_id>/update",
    methods=["POST"],
)
@login_required("admin")
def admin_update_option_group(item_id: int, group_id: int):
    group = db_session.get(MenuOptionGroup, group_id)
    if not group or group.menu_item_id != item_id:
        abort(404, description="Option group not found")

    name = request.form.get("name", group.name).strip()
    selection_type = _normalize_selection_type(request.form.get("selection_type"))
    is_required = request.form.get("is_required") == "on"
    position_raw = request.form.get("position", "").strip()

    if not name:
        flash("กรุณาระบุชื่อกลุ่มตัวเลือก", "error")
        return redirect(url_for("main.admin_manage_menu"))

    try:
        position = int(position_raw) if position_raw else group.position
    except ValueError:
        flash("ลำดับต้องเป็นตัวเลข", "error")
        return redirect(url_for("main.admin_manage_menu"))

    group.name = name
    group.selection_type = selection_type
    group.is_required = is_required
    group.position = position

    db_session.commit()
    flash("อัปเดตกลุ่มตัวเลือกเรียบร้อย", "success")
    return redirect(url_for("main.admin_manage_menu"))


@main_blueprint.route(
    "/admin/menu/items/<int:item_id>/option-groups/<int:group_id>/delete",
    methods=["POST"],
)
@login_required("admin")
def admin_delete_option_group(item_id: int, group_id: int):
    group = db_session.get(MenuOptionGroup, group_id)
    if not group or group.menu_item_id != item_id:
        abort(404, description="Option group not found")

    db_session.delete(group)
    db_session.commit()
    flash("ลบกลุ่มตัวเลือกเรียบร้อย", "success")
    return redirect(url_for("main.admin_manage_menu"))


@main_blueprint.route(
    "/admin/menu/items/<int:item_id>/option-groups/<int:group_id>/options",
    methods=["POST"],
)
@login_required("admin")
def admin_add_menu_option(item_id: int, group_id: int):
    group = db_session.get(MenuOptionGroup, group_id)
    if not group or group.menu_item_id != item_id:
        abort(404, description="Option group not found")

    name = request.form.get("name", "").strip()
    price_raw = request.form.get("price", "").strip()
    position_raw = request.form.get("position", "").strip()

    if not name:
        flash("กรุณาระบุชื่อตัวเลือก", "error")
        return redirect(url_for("main.admin_manage_menu"))

    try:
        price_delta = round(float(price_raw), 2) if price_raw else 0.0
    except (TypeError, ValueError):
        flash("ราคาที่เพิ่มต้องเป็นตัวเลข", "error")
        return redirect(url_for("main.admin_manage_menu"))

    try:
        position = int(position_raw) if position_raw else 0
    except ValueError:
        flash("ลำดับต้องเป็นตัวเลข", "error")
        return redirect(url_for("main.admin_manage_menu"))

    option = MenuOption(
        group=group,
        name=name,
        price_delta=price_delta,
        position=position,
    )
    db_session.add(option)
    db_session.commit()
    flash("เพิ่มตัวเลือกเรียบร้อย", "success")
    return redirect(url_for("main.admin_manage_menu"))


@main_blueprint.route(
    "/admin/menu/items/<int:item_id>/option-groups/<int:group_id>/options/<int:option_id>/update",
    methods=["POST"],
)
@login_required("admin")
def admin_update_menu_option(item_id: int, group_id: int, option_id: int):
    option = db_session.get(MenuOption, option_id)
    if not option or option.group_id != group_id or option.group.menu_item_id != item_id:
        abort(404, description="Option not found")

    name = request.form.get("name", option.name).strip()
    price_raw = request.form.get("price", "").strip()
    position_raw = request.form.get("position", "").strip()

    if not name:
        flash("กรุณาระบุชื่อตัวเลือก", "error")
        return redirect(url_for("main.admin_manage_menu"))

    try:
        option.price_delta = round(float(price_raw), 2) if price_raw else 0.0
    except (TypeError, ValueError):
        flash("ราคาที่เพิ่มต้องเป็นตัวเลข", "error")
        return redirect(url_for("main.admin_manage_menu"))

    try:
        option.position = int(position_raw) if position_raw else option.position
    except ValueError:
        flash("ลำดับต้องเป็นตัวเลข", "error")
        return redirect(url_for("main.admin_manage_menu"))

    option.name = name

    db_session.commit()
    flash("อัปเดตตัวเลือกเรียบร้อย", "success")
    return redirect(url_for("main.admin_manage_menu"))


@main_blueprint.route(
    "/admin/menu/items/<int:item_id>/option-groups/<int:group_id>/options/<int:option_id>/delete",
    methods=["POST"],
)
@login_required("admin")
def admin_delete_menu_option(item_id: int, group_id: int, option_id: int):
    option = db_session.get(MenuOption, option_id)
    if not option or option.group_id != group_id or option.group.menu_item_id != item_id:
        abort(404, description="Option not found")

    db_session.delete(option)
    db_session.commit()
    flash("ลบตัวเลือกเรียบร้อย", "success")
    return redirect(url_for("main.admin_manage_menu"))


@main_blueprint.route("/admin/menu/items/<int:item_id>/delete", methods=["POST"])
@login_required("adminpp")
def admin_delete_menu_item(item_id: int):
    menu_item = db_session.get(MenuItem, item_id)
    if not menu_item:
        abort(404, description="Menu item not found")

    if menu_item.order_items:
        flash("ไม่สามารถลบเมนูที่ถูกใช้ในออเดอร์แล้ว", "error")
        return redirect(url_for("main.admin_manage_menu"))

    _remove_menu_image(menu_item.image_path)
    db_session.delete(menu_item)
    db_session.commit()
    flash("ลบเมนูเรียบร้อย", "success")
    return redirect(url_for("main.admin_manage_menu"))


@main_blueprint.route("/admin/tables")
@login_required("admin")
def admin_manage_tables():
    tables = db_session.scalars(
        select(DiningTable).order_by(DiningTable.name.asc())
    ).all()
    total_counts = dict(
        db_session.query(Order.table_id, func.count(Order.id)).group_by(Order.table_id).all()
    )
    active_counts = dict(
        db_session.query(Order.table_id, func.count(Order.id))
        .filter(Order.status != OrderStatusEnum.PAID.value)
        .group_by(Order.table_id)
        .all()
    )
    return render_template(
        "admin/tables.html",
        tables=tables,
        total_counts=total_counts,
        active_counts=active_counts,
        highlight_id=request.args.get("highlight", type=int),
    )


@main_blueprint.route("/admin/tables/create", methods=["POST"])
@login_required("admin")
def admin_create_table_entry():
    name = request.form.get("name", "").strip()
    code = request.form.get("code", "").strip().upper()

    if not name or not code:
        flash("กรุณาระบุชื่อและรหัสโต๊ะ", "error")
        return redirect(url_for("main.admin_manage_tables"))

    if db_session.scalar(select(DiningTable).where(DiningTable.code == code)):
        flash("รหัสโต๊ะนี้ถูกใช้งานแล้ว", "error")
        return redirect(url_for("main.admin_manage_tables"))

    table = DiningTable(name=name, code=code)
    table.access_token = secrets.token_hex(16)
    db_session.add(table)
    db_session.commit()
    flash("เพิ่มโต๊ะใหม่เรียบร้อย", "success")
    return redirect(url_for("main.admin_manage_tables", highlight=table.id))


@main_blueprint.route("/admin/tables/<int:table_id>/update", methods=["POST"])
@login_required("admin")
def admin_update_table_entry(table_id: int):
    table = db_session.get(DiningTable, table_id)
    if not table:
        abort(404, description="Table not found")

    name = request.form.get("name", table.name).strip()
    code = request.form.get("code", table.code).strip().upper()

    if not name or not code:
        flash("กรุณาระบุชื่อและรหัสโต๊ะ", "error")
        return redirect(url_for("main.admin_manage_tables"))

    duplicate = (
        db_session.query(DiningTable)
        .filter(DiningTable.id != table.id, DiningTable.code == code)
        .first()
    )
    if duplicate:
        flash("รหัสโต๊ะนี้ถูกใช้งานแล้ว", "error")
        return redirect(url_for("main.admin_manage_tables"))

    table.name = name
    table.code = code
    db_session.commit()
    flash("บันทึกการแก้ไขโต๊ะเรียบร้อย", "success")
    return redirect(url_for("main.admin_manage_tables", highlight=table.id))


@main_blueprint.route("/admin/tables/<int:table_id>/delete", methods=["POST"])
@login_required("admin")
def admin_delete_table_entry(table_id: int):
    table = db_session.get(DiningTable, table_id)
    if not table:
        abort(404, description="Table not found")

    has_orders = (
        db_session.query(Order.id)
        .filter(Order.table_id == table.id)
        .limit(1)
        .scalar()
    )
    if has_orders:
        flash("ไม่สามารถลบโต๊ะที่มีประวัติคำสั่งซื้อ", "error")
        return redirect(url_for("main.admin_manage_tables"))

    db_session.delete(table)
    db_session.commit()
    flash("ลบโต๊ะเรียบร้อย", "success")
    return redirect(url_for("main.admin_manage_tables"))


@main_blueprint.route("/admin/tables/<int:table_id>/token", methods=["POST"])
@login_required("admin")
def admin_regenerate_table_token(table_id: int):
    table = db_session.get(DiningTable, table_id)
    if not table:
        abort(404, description="Table not found")
    table.access_token = secrets.token_hex(16)
    db_session.commit()
    flash("สร้างโทเคนใหม่สำหรับโต๊ะเรียบร้อย", "success")
    return redirect(url_for("main.admin_manage_tables", highlight=table.id))


@main_blueprint.route("/admin/tables/<int:table_id>/qr.png")
@login_required("admin")
def admin_table_qr_image(table_id: int):
    table = db_session.get(DiningTable, table_id)
    if not table:
        abort(404, description="Table not found")

    params = {}
    if table.access_token:
        params["token"] = table.access_token
    target_url = _build_table_menu_url(table.code)
    if params:
        query = urllib.parse.urlencode(params)
        target_url = f"{target_url}?{query}"
    qr = qrcode.QRCode(version=2, border=3)
    qr.add_data(target_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    filename = f"table_{table.code}.png"
    download = request.args.get("download") == "1"
    response = send_file(
        buffer,
        mimetype="image/png",
        as_attachment=download,
        download_name=filename,
    )
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return response


def _build_table_menu_url(table_code: str) -> str:
    base_url = current_app.config.get("TABLE_MENU_BASE_URL")
    path = url_for("main.table_menu", table_code=table_code)
    if base_url:
        return f"{base_url.rstrip('/')}{path}"
    return url_for("main.table_menu", table_code=table_code, _external=True)


@main_blueprint.route("/admin/reset-data", methods=["POST"])
@login_required("admin")
def admin_reset_data():
    try:
        seed_sample_data(force=True)
        flash("ล้างข้อมูลทั้งหมดและสร้างโต๊ะเริ่มต้นเรียบร้อย", "success")
    except Exception as exc:  # pragma: no cover - defensive
        db_session.rollback()
        current_app.logger.error("Failed to reset data: %s", exc, exc_info=True)
        flash("ไม่สามารถรีเซ็ตข้อมูลได้", "error")
    return redirect(url_for("main.admin_manage_tables"))


@main_blueprint.route("/admin/stock")
@login_required("admin")
def admin_stock_dashboard():
    ingredients = db_session.scalars(
        select(Ingredient).order_by(Ingredient.name.asc())
    ).all()
    low_stock = [
        ingredient
        for ingredient in ingredients
        if ingredient.quantity_on_hand <= ingredient.reorder_level
    ]
    recent_movements = (
        db_session.query(StockMovement)
        .order_by(StockMovement.created_at.desc())
        .limit(20)
        .all()
    )
    return render_template(
        "admin/stock.html",
        ingredients=ingredients,
        low_stock=low_stock,
        recent_movements=recent_movements,
    )


@main_blueprint.route("/admin/stock/ingredients", methods=["POST"])
@login_required("admin")
def admin_create_ingredient():
    name = request.form.get("name", "").strip()
    unit = request.form.get("unit", "หน่วย").strip() or "หน่วย"
    quantity_raw = request.form.get("quantity_on_hand", "").strip()
    reorder_raw = request.form.get("reorder_level", "").strip()

    if not name:
        flash("กรุณากรอกชื่อวัตถุดิบ", "error")
        return redirect(url_for("main.admin_stock_dashboard"))

    try:
        quantity = max(0.0, float(quantity_raw) if quantity_raw else 0.0)
    except (TypeError, ValueError):
        quantity = 0.0

    try:
        reorder_level = max(0.0, float(reorder_raw) if reorder_raw else 0.0)
    except (TypeError, ValueError):
        reorder_level = 0.0

    ingredient = Ingredient(
        name=name,
        unit=unit,
        quantity_on_hand=quantity,
        reorder_level=reorder_level,
    )
    db_session.add(ingredient)
    db_session.flush()

    if quantity > 0:
        db_session.add(
            StockMovement(
                ingredient=ingredient,
                change=quantity,
                movement_type=StockMovementTypeEnum.RESTOCK.value,
                note="เพิ่มวัตถุดิบใหม่",
            )
        )

    db_session.commit()
    flash("เพิ่มวัตถุดิบใหม่เรียบร้อย", "success")
    return redirect(url_for("main.admin_stock_dashboard"))


@main_blueprint.route(
    "/admin/stock/ingredients/<int:ingredient_id>/restock", methods=["POST"]
)
@login_required("admin")
def admin_restock_ingredient(ingredient_id: int):
    ingredient = db_session.get(Ingredient, ingredient_id)
    if not ingredient:
        abort(404, description="Ingredient not found")

    amount_raw = request.form.get("amount", "").strip()
    note = request.form.get("note", "").strip() or "เติมสต๊อก"

    try:
        amount = round(float(amount_raw), 2)
    except (TypeError, ValueError):
        flash("จำนวนที่เติมไม่ถูกต้อง", "error")
        return redirect(url_for("main.admin_stock_dashboard"))

    if amount <= 0:
        flash("จำนวนที่เติมต้องมากกว่า 0", "error")
        return redirect(url_for("main.admin_stock_dashboard"))

    ingredient.quantity_on_hand = float(ingredient.quantity_on_hand or 0) + amount
    db_session.add(
        StockMovement(
            ingredient=ingredient,
            change=amount,
            movement_type=StockMovementTypeEnum.RESTOCK.value,
            note=note,
        )
    )

    affected_menu_items = [link.menu_item for link in ingredient.menu_links]
    _update_menu_item_availability(affected_menu_items)
    db_session.commit()
    flash("เติมสต๊อกเรียบร้อย", "success")
    return redirect(url_for("main.admin_stock_dashboard"))


@main_blueprint.route(
    "/admin/stock/ingredients/<int:ingredient_id>/adjust", methods=["POST"]
)
@login_required("admin")
def admin_adjust_ingredient(ingredient_id: int):
    ingredient = db_session.get(Ingredient, ingredient_id)
    if not ingredient:
        abort(404, description="Ingredient not found")

    new_quantity_raw = request.form.get("new_quantity", "").strip()
    note = request.form.get("note", "").strip() or "ปรับยอดคงเหลือ"

    try:
        new_quantity = max(0.0, float(new_quantity_raw))
    except (TypeError, ValueError):
        flash("จำนวนใหม่ไม่ถูกต้อง", "error")
        return redirect(url_for("main.admin_stock_dashboard"))

    current_qty = float(ingredient.quantity_on_hand or 0)
    change = round(new_quantity - current_qty, 2)
    ingredient.quantity_on_hand = new_quantity

    db_session.add(
        StockMovement(
            ingredient=ingredient,
            change=change,
            movement_type=StockMovementTypeEnum.ADJUSTMENT.value,
            note=note,
        )
    )

    affected_menu_items = [link.menu_item for link in ingredient.menu_links]
    _update_menu_item_availability(affected_menu_items)
    db_session.commit()
    flash("ปรับยอดคงเหลือเรียบร้อย", "success")
    return redirect(url_for("main.admin_stock_dashboard"))


@main_blueprint.route("/admin/stock/movements")
@login_required("admin")
def admin_stock_movements():
    movements = (
        db_session.query(StockMovement)
        .order_by(StockMovement.created_at.desc())
        .limit(200)
        .all()
    )
    return render_template("admin/stock_movements.html", movements=movements)


@main_blueprint.route("/admin/reports")
@login_required("admin")
def admin_reports():
    paid_orders = (
        db_session.query(Order)
        .filter(Order.status == OrderStatusEnum.PAID.value)
        .order_by(Order.paid_at.desc().nullslast(), Order.created_at.desc())
        .all()
    )

    daily_summary: Dict[str, Dict[str, float]] = defaultdict(
        lambda: {"total": 0.0, "count": 0.0, "items": 0.0}
    )
    monthly_summary: Dict[str, Dict[str, float]] = defaultdict(
        lambda: {"total": 0.0, "count": 0.0, "items": 0.0}
    )
    payment_breakdown: Dict[str, float] = defaultdict(float)

    total_revenue = 0.0
    total_orders = 0
    total_items = 0

    for order in paid_orders:
        paid_time = order.paid_at or order.created_at
        day_key = paid_time.date().isoformat()
        month_key = paid_time.strftime("%Y-%m")
        order_total = order.grand_total
        items_count = sum(item.quantity for item in order.items)

        daily_summary[day_key]["total"] += order_total
        daily_summary[day_key]["count"] += 1
        daily_summary[day_key]["items"] += items_count

        monthly_summary[month_key]["total"] += order_total
        monthly_summary[month_key]["count"] += 1
        monthly_summary[month_key]["items"] += items_count

        for payment in order.payments:
            payment_breakdown[payment.method] += float(payment.amount)

        total_revenue += order_total
        total_orders += 1
        total_items += items_count

    daily_rows = [
        {
            "day": day,
            "total": round(data["total"], 2),
            "order_count": int(data["count"]),
            "item_count": int(data["items"]),
        }
        for day, data in sorted(daily_summary.items(), key=lambda item: item[0], reverse=True)
    ]

    monthly_rows = [
        {
            "month": month,
            "total": round(data["total"], 2),
            "order_count": int(data["count"]),
            "item_count": int(data["items"]),
        }
        for month, data in sorted(
            monthly_summary.items(),
            key=lambda item: item[0],
            reverse=True,
        )
    ]

    payment_rows = [
        {
            "method": method,
            "label": PAYMENT_METHOD_LABELS.get(method, method),
            "total": round(amount, 2),
        }
        for method, amount in sorted(
            payment_breakdown.items(), key=lambda item: item[1], reverse=True
        )
    ]

    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    top_items = (
        db_session.query(
            MenuItem.name,
            func.sum(OrderItem.quantity).label("qty"),
            func.sum(
                OrderItem.quantity * func.coalesce(OrderItem.unit_price, MenuItem.price)
            ).label("value"),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .filter(Order.status == OrderStatusEnum.PAID.value)
        .filter(Order.paid_at.is_not(None))
        .filter(Order.paid_at >= thirty_days_ago)
        .group_by(MenuItem.name)
        .order_by(func.sum(OrderItem.quantity).desc())
        .limit(10)
        .all()
    )

    return render_template(
        "admin/reports.html",
        daily_rows=daily_rows,
        monthly_rows=monthly_rows,
        payment_rows=payment_rows,
        total_revenue=round(total_revenue, 2),
        total_orders=total_orders,
        total_items=total_items,
        top_items=top_items,
    )


@main_blueprint.route("/admin/insights")
@login_required("admin")
def admin_insights():
    now = datetime.utcnow()
    seven_days_ago = now - timedelta(days=6)
    thirty_days_ago = now - timedelta(days=30)

    price_expr = OrderItem.quantity * func.coalesce(
        OrderItem.unit_price, MenuItem.price
    )

    paid_filter = [
        Order.status == OrderStatusEnum.PAID.value,
        Order.paid_at.is_not(None),
    ]

    total_orders_30 = (
        db_session.query(func.count(Order.id))
        .filter(*paid_filter, Order.paid_at >= thirty_days_ago)
        .scalar()
        or 0
    )
    total_revenue_30 = (
        db_session.query(func.coalesce(func.sum(price_expr), 0))
        .select_from(Order)
        .join(OrderItem, Order.id == OrderItem.order_id)
        .join(MenuItem, MenuItem.id == OrderItem.menu_item_id)
        .filter(*paid_filter, Order.paid_at >= thirty_days_ago)
        .scalar()
        or 0
    )
    avg_order_value = total_revenue_30 / total_orders_30 if total_orders_30 else 0

    daily_rows = (
        db_session.query(
            func.strftime("%Y-%m-%d", Order.paid_at).label("day"),
            func.count(Order.id).label("count"),
            func.coalesce(func.sum(price_expr), 0).label("revenue"),
        )
        .select_from(Order)
        .join(OrderItem, Order.id == OrderItem.order_id)
        .join(MenuItem, MenuItem.id == OrderItem.menu_item_id)
        .filter(*paid_filter, Order.paid_at >= seven_days_ago)
        .group_by("day")
        .order_by("day")
        .all()
    )
    daily_chart = {
        "labels": [row.day for row in daily_rows],
        "orders": [int(row.count) for row in daily_rows],
        "revenue": [float(row.revenue or 0) for row in daily_rows],
    }

    hourly_rows = (
        db_session.query(
            func.strftime("%H", Order.paid_at).label("hour"),
            func.count(Order.id).label("count"),
        )
        .filter(*paid_filter, Order.paid_at >= seven_days_ago)
        .group_by("hour")
        .order_by("hour")
        .all()
    )
    hourly_labels = [f"{int(row.hour):02d}:00" for row in hourly_rows]
    hourly_counts = [int(row.count) for row in hourly_rows]
    busy_hour = "-"
    if hourly_counts:
        idx = hourly_counts.index(max(hourly_counts))
        busy_hour = hourly_labels[idx]

    best_items = (
        db_session.query(
            MenuItem.name,
            func.sum(OrderItem.quantity).label("qty"),
        )
        .select_from(Order)
        .join(OrderItem, Order.id == OrderItem.order_id)
        .join(MenuItem, MenuItem.id == OrderItem.menu_item_id)
        .filter(*paid_filter, Order.paid_at >= thirty_days_ago)
        .group_by(MenuItem.id, MenuItem.name)
        .order_by(func.sum(OrderItem.quantity).desc())
        .limit(5)
        .all()
    )

    top_categories = (
        db_session.query(
            MenuCategory.name,
            func.sum(OrderItem.quantity).label("qty"),
        )
        .select_from(Order)
        .join(OrderItem, Order.id == OrderItem.order_id)
        .join(MenuItem, MenuItem.id == OrderItem.menu_item_id)
        .join(MenuCategory, MenuCategory.id == MenuItem.category_id)
        .filter(*paid_filter, Order.paid_at >= thirty_days_ago)
        .group_by(MenuCategory.id, MenuCategory.name)
        .order_by(func.sum(OrderItem.quantity).desc())
        .limit(5)
        .all()
    )
    category_chart = {
        "labels": [row.name for row in top_categories],
        "data": [int(row.qty) for row in top_categories],
    }

    payment_rows = (
        db_session.query(
            Payment.method,
            func.count(Payment.id).label("count"),
            func.coalesce(func.sum(Payment.amount), 0).label("total"),
        )
        .filter(Payment.paid_at >= thirty_days_ago)
        .group_by(Payment.method)
        .all()
    )
    payment_share = [
        {
            "method": row.method,
            "label": PAYMENT_METHOD_LABELS.get(row.method, row.method),
            "orders": int(row.count),
            "total": float(row.total or 0),
        }
        for row in payment_rows
    ]

    top_tables_rows = (
        db_session.query(
            DiningTable.name,
            DiningTable.code,
            func.count(Order.id).label("order_count"),
            func.coalesce(func.sum(price_expr), 0).label("revenue"),
        )
        .select_from(Order)
        .join(DiningTable, DiningTable.id == Order.table_id)
        .join(OrderItem, OrderItem.order_id == Order.id)
        .join(MenuItem, MenuItem.id == OrderItem.menu_item_id)
        .filter(*paid_filter, Order.paid_at >= thirty_days_ago)
        .group_by(DiningTable.id)
        .order_by(func.sum(price_expr).desc())
        .limit(5)
        .all()
    )
    top_tables = [
        {
            "name": row.name,
            "code": row.code,
            "orders": int(row.order_count),
            "revenue": float(row.revenue or 0),
        }
        for row in top_tables_rows
    ]

    summary = {
        "revenue_30": float(total_revenue_30),
        "orders_30": total_orders_30,
        "avg_order_value": float(avg_order_value),
        "top_item": best_items[0].name if best_items else "-",
        "top_item_qty": int(best_items[0].qty) if best_items else 0,
        "busy_hour": busy_hour,
        "top_table": top_tables[0] if top_tables else None,
    }

    return render_template(
        "admin/insights.html",
        summary=summary,
        daily_chart=daily_chart,
        hourly_chart={"labels": hourly_labels, "data": hourly_counts},
        category_chart=category_chart,
        payment_share=payment_share,
        top_items=[{"name": row.name, "qty": int(row.qty)} for row in best_items],
        top_tables=top_tables,
    )


def _collect_orders(statuses: List[str]) -> List[Dict[str, Any]]:
    orders = (
        db_session.query(Order)
        .filter(Order.status.in_(statuses))
        .order_by(Order.created_at.asc())
        .all()
    )
    return [_order_to_dict(order) for order in orders]


def _collect_noodle_orders() -> List[tuple[Order, List[Dict[str, Any]]]]:
    orders = (
        db_session.query(Order)
        .options(
            selectinload(Order.items)
            .selectinload(OrderItem.menu_item)
            .selectinload(MenuItem.category)
        )
        .filter(Order.status != OrderStatusEnum.PAID.value)
        .order_by(Order.created_at.asc())
        .all()
    )

    result: List[tuple[Order, List[Dict[str, Any]]]] = []
    for order in orders:
        noodle_items: List[Dict[str, Any]] = []
        for item in order.items:
            category_name = (item.menu_item.category.name if item.menu_item and item.menu_item.category else "")
            if "ก๋วยเตี๋ยว" not in (category_name or ""):
                continue
            details = _parse_order_item_details(item.note)
            noodle_items.append(
                {
                    "name": item.menu_item.name if item.menu_item else "-",
                    "quantity": item.quantity,
                    "noodle": details["noodle"],
                    "extras": details["extras"],
                    "other": details["other"],
                }
            )
        if noodle_items:
            result.append((order, noodle_items))
    return result


def _backfill_invoices(order_ids: List[int] | None = None) -> None:
    query = db_session.query(Order).filter(Order.status == OrderStatusEnum.PAID.value)
    if order_ids:
        query = query.filter(Order.id.in_(order_ids))
    missing_orders = query.filter(~Order.invoice.has()).all()
    if not missing_orders:
        return
    for order in missing_orders:
        _ensure_invoice(order)
    db_session.commit()


def _render_invoice_image(invoice: Invoice) -> io.BytesIO:
    order = invoice.order
    width, height = 800, 1100
    margin = 60
    bg_color = (255, 248, 236)
    text_color = (63, 42, 32)
    accent_color = (211, 116, 51)

    image = Image.new("RGB", (width, height), color=bg_color)
    draw = ImageDraw.Draw(image)

    try:
        font_regular = ImageFont.truetype("Arial Unicode.ttf", 28)
        font_small = ImageFont.truetype("Arial Unicode.ttf", 22)
        font_bold = ImageFont.truetype("Arial Unicode.ttf", 42)
        font_subtitle = ImageFont.truetype("Arial Unicode.ttf", 28)
    except IOError:
        font_regular = ImageFont.load_default()
        font_small = ImageFont.load_default()
        font_bold = ImageFont.load_default()
        font_subtitle = ImageFont.load_default()

    # Logo
    logo_path = Path("static/img/logo.jpg")
    logo_size = (120, 120)
    if logo_path.exists():
        logo = Image.open(logo_path).convert("RGB")
        logo.thumbnail(logo_size, Image.LANCZOS)
        image.paste(logo, (margin, margin))
    draw.text((margin + 140, margin + 10), "9เครือ POS", font=font_bold, fill=accent_color)
    draw.text(
        (margin + 140, margin + 60),
        "ก๋วยเตี๋ยวต้มยำสุโขทัย",
        font=font_subtitle,
        fill=text_color,
    )
    draw.text(
        (margin + 140, margin + 100),
        f"Invoice #{invoice.id}",
        font=font_regular,
        fill=text_color,
    )
    draw.text(
        (margin + 140, margin + 135),
        invoice.created_at.strftime("%Y-%m-%d %H:%M"),
        font=font_small,
        fill=text_color,
    )

    # Table info
    y = margin + 200
    draw.text((margin, y), f"Order #{order.id} at {order.table.name} ({order.table.code})", font=font_regular, fill=text_color)
    y += 40
    draw.text((margin, y), f"Paid at {order.paid_at.strftime('%Y-%m-%d %H:%M') if order.paid_at else '-'}", font=font_small, fill=text_color)
    y += 40

    draw.line((margin, y, width - margin, y), fill=accent_color, width=3)
    y += 20
    draw.text((margin, y), "รายการอาหาร", font=font_bold, fill=accent_color)
    y += 40

    for item in order.items:
        draw.text(
            (margin, y),
            f"{item.quantity} x {item.menu_item.name}",
            font=font_regular,
            fill=text_color,
        )
        line_total = f"{float(item.subtotal):.2f} ฿"
        draw.text((width - margin - 200, y), line_total, font=font_regular, fill=text_color)
        y += 30
        if item.note:
            draw.text((margin + 20, y), f"หมายเหตุ: {item.note}", font=font_small, fill=text_color)
            y += 25
        y += 10

    y += 10
    draw.line((margin, y, width - margin, y), fill=accent_color, width=2)
    y += 25

    totals = [
        ("มูลค่าสินค้า", float(invoice.net_amount)),
        ("VAT 7%", float(invoice.tax_amount)),
        ("ยอดรวมสุทธิ", float(invoice.total_amount)),
    ]
    for label, value in totals:
        draw.text((margin, y), label, font=font_regular, fill=text_color)
        draw.text((width - margin - 200, y), f"{value:.2f} ฿", font=font_regular, fill=text_color)
        y += 35

    draw.text(
        (margin, y + 20),
        "ขอบคุณที่อุดหนุน 9 เครือ ก๋วยเตี๋ยวสุโขทัย",
        font=font_small,
        fill=accent_color,
    )

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


def _ensure_invoice(order: Order) -> Invoice:
    if order.invoice:
        return order.invoice

    total_decimal = Decimal(str(getattr(order, "grand_total", order.total)))
    tax_decimal = (total_decimal * INVOICE_TAX_RATE).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    net_decimal = (total_decimal - tax_decimal).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    invoice = Invoice(
        order=order,
        total_amount=float(total_decimal),
        net_amount=float(net_decimal),
        tax_amount=float(tax_decimal),
        tax_rate=float(INVOICE_TAX_PERCENT),
    )
    db_session.add(invoice)
    return invoice


def _order_to_dict(order: Order) -> Dict[str, Any]:
    return {
        "id": order.id,
        "table": order.table.name,
        "table_code": order.table.code,
        "status": order.status,
        "status_label": STATUS_LABELS.get(order.status, order.status),
        "status_hint": STATUS_HINTS.get(order.status, ""),
        "note": order.note,
        "created_at": order.created_at.isoformat(),
        "total": order.total,
        "items": [
            {
                "id": item.id,
                "menu_item_id": item.menu_item_id,
                "name": item.menu_item.name,
                "quantity": item.quantity,
                "note": item.note,
                "price": float(item.unit_price if item.unit_price is not None else item.menu_item.price),
                "unit_price": float(item.unit_price if item.unit_price is not None else item.menu_item.price),
                "subtotal": item.subtotal,
                "image": (
                    url_for("static", filename=item.menu_item.image_path)
                    if item.menu_item.image_path
                    else None
                ),
            }
            for item in order.items
        ],
        "subtotal": order.subtotal,
        "discount": order.discount,
        "service_charge": order.service,
        "tax_rate": order.tax_percentage,
        "tax_amount": order.tax_amount,
        "grand_total": order.grand_total,
        "amount_paid": order.amount_paid,
        "balance_due": order.balance_due,
        "paid_at": order.paid_at.isoformat() if order.paid_at else None,
        "invoice_id": order.invoice.id if order.invoice else None,
        "payments": [
            {
                "id": payment.id,
                "amount": float(payment.amount),
                "method": payment.method,
                "method_label": PAYMENT_METHOD_LABELS.get(payment.method, payment.method),
                "reference": payment.reference,
                "note": payment.note,
                "paid_at": payment.paid_at.isoformat(),
            }
            for payment in order.payments
        ],
    }


def _calculate_inventory_usage(
    menu_pairs: Iterable[Tuple[MenuItem, int]]
) -> Tuple[Dict[int, Dict[str, Any]], List[MenuItem]]:
    usage: Dict[int, Dict[str, Any]] = {}
    affected_menu_items: List[MenuItem] = []

    for menu_item, quantity in menu_pairs:
        if not menu_item or quantity <= 0:
            continue
        affected_menu_items.append(menu_item)
        for link in menu_item.ingredients:
            ingredient = link.ingredient
            if not ingredient:
                continue
            required = float(link.quantity or 0) * quantity
            info = usage.setdefault(
                ingredient.id,
                {
                    "ingredient": ingredient,
                    "required": 0.0,
                },
            )
            info["required"] += required

    return usage, affected_menu_items


def _reserve_stock_for_order(
    order: Order,
    usage_totals: Dict[int, Dict[str, Any]],
    affected_menu_items: Iterable[MenuItem],
) -> None:
    if not usage_totals:
        return

    for data in usage_totals.values():
        ingredient: Ingredient = data["ingredient"]
        required = round(data["required"], 2)
        if not ingredient.is_active:
            db_session.rollback()
            abort(400, description=f"วัตถุดิบ {ingredient.name} ถูกปิดใช้งาน")
        available = float(ingredient.quantity_on_hand or 0)
        if available < required:
            db_session.rollback()
            abort(
                400,
                description=(
                    f"วัตถุดิบ {ingredient.name} เหลือ {available:.2f} {ingredient.unit} "
                    f"ไม่เพียงพอ (ต้องการ {required:.2f})"
                ),
            )

    db_session.flush()

    expanded_menu_items = set(affected_menu_items)
    for data in usage_totals.values():
        ingredient: Ingredient = data["ingredient"]
        required = round(data["required"], 2)
        new_quantity = float(ingredient.quantity_on_hand or 0) - required
        ingredient.quantity_on_hand = new_quantity
        db_session.add(
            StockMovement(
                ingredient=ingredient,
                change=-required,
                movement_type=StockMovementTypeEnum.USAGE.value,
                note=f"เบิกสำหรับออเดอร์ #{order.id}",
            )
        )
        for link in ingredient.menu_links:
            expanded_menu_items.add(link.menu_item)

    _update_menu_item_availability(expanded_menu_items)


def _release_stock_for_order(order: Order) -> None:
    if not order.items:
        return

    menu_pairs = []
    for item in order.items:
        if not item.menu_item:
            continue
        menu_pairs.append((item.menu_item, item.quantity))

    if not menu_pairs:
        return

    usage_totals, affected_menu_items = _calculate_inventory_usage(menu_pairs)
    if not usage_totals:
        return

    expanded_menu_items = set(affected_menu_items)
    for data in usage_totals.values():
        ingredient: Ingredient = data["ingredient"]
        amount = round(data["required"], 2)
        ingredient.quantity_on_hand = float(ingredient.quantity_on_hand or 0) + amount
        db_session.add(
            StockMovement(
                ingredient=ingredient,
                change=amount,
                movement_type=StockMovementTypeEnum.ADJUSTMENT.value,
                note=f"คืนสต๊อกจากการยกเลิกออเดอร์ #{order.id}",
            )
        )
        for link in ingredient.menu_links:
            expanded_menu_items.add(link.menu_item)

    _update_menu_item_availability(expanded_menu_items)


def _update_menu_item_availability(menu_items: Iterable[MenuItem]) -> None:
    unique_items: Dict[int, MenuItem] = {}
    fallback_items: Dict[int, MenuItem] = {}

    for menu_item in menu_items:
        if not menu_item:
            continue
        identity = getattr(menu_item, "id", None)
        if identity is not None:
            if identity in unique_items:
                continue
            unique_items[identity] = menu_item
        else:
            key = id(menu_item)
            if key in fallback_items:
                continue
            fallback_items[key] = menu_item

    for menu_item in [*unique_items.values(), *fallback_items.values()]:
        if not menu_item.ingredients:
            menu_item.is_available = True
            continue
        is_available = True
        for link in menu_item.ingredients:
            ingredient = link.ingredient
            if not ingredient or not ingredient.is_active:
                is_available = False
                break
            available = float(ingredient.quantity_on_hand or 0)
            required = float(link.quantity or 0)
            if available < required:
                is_available = False
                break
        menu_item.is_available = is_available
