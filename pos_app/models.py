from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import List

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base, db_session


class Setting(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<Setting {self.key}>"


class DiningTable(Base):
    __tablename__ = "dining_tables"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    access_token: Mapped[str | None] = mapped_column(String(64), nullable=True)

    orders: Mapped[List["Order"]] = relationship(
        "Order", back_populates="table", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<DiningTable {self.code}>"


class MenuCategory(Base):
    __tablename__ = "menu_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    items: Mapped[List["MenuItem"]] = relationship(
        "MenuItem",
        back_populates="category",
        cascade="all, delete-orphan",
        order_by="MenuItem.position",
    )

    def __repr__(self) -> str:
        return f"<MenuCategory {self.name}>"


class Ingredient(Base):
    __tablename__ = "ingredients"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    unit: Mapped[str] = mapped_column(String(50), default="หน่วย", nullable=False)
    quantity_on_hand: Mapped[float] = mapped_column(Numeric(10, 2), default=0, nullable=False)
    reorder_level: Mapped[float] = mapped_column(Numeric(10, 2), default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    menu_links: Mapped[List["MenuItemIngredient"]] = relationship(
        "MenuItemIngredient",
        back_populates="ingredient",
        cascade="all, delete-orphan",
    )
    movements: Mapped[List["StockMovement"]] = relationship(
        "StockMovement",
        back_populates="ingredient",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Ingredient {self.name}>"


class MenuItem(Base):
    __tablename__ = "menu_items"
    __table_args__ = (UniqueConstraint("name", "category_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    is_available: Mapped[bool] = mapped_column(default=True, nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    image_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    allow_special: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    special_price_delta: Mapped[float] = mapped_column(Numeric(10, 2), default=0, nullable=False)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("menu_categories.id"), nullable=False
    )

    category: Mapped["MenuCategory"] = relationship("MenuCategory", back_populates="items")
    order_items: Mapped[List["OrderItem"]] = relationship("OrderItem", back_populates="menu_item")
    ingredients: Mapped[List["MenuItemIngredient"]] = relationship(
        "MenuItemIngredient",
        back_populates="menu_item",
        cascade="all, delete-orphan",
        order_by="MenuItemIngredient.id",
    )
    option_groups: Mapped[List["MenuOptionGroup"]] = relationship(
        "MenuOptionGroup",
        back_populates="menu_item",
        cascade="all, delete-orphan",
        order_by="MenuOptionGroup.position",
    )

    def __repr__(self) -> str:
        return f"<MenuItem {self.name}>"


class MenuItemIngredient(Base):
    __tablename__ = "menu_item_ingredients"
    __table_args__ = (UniqueConstraint("menu_item_id", "ingredient_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    menu_item_id: Mapped[int] = mapped_column(
        ForeignKey("menu_items.id"), nullable=False
    )
    ingredient_id: Mapped[int] = mapped_column(
        ForeignKey("ingredients.id"), nullable=False
    )
    quantity: Mapped[float] = mapped_column(Numeric(10, 2), default=0, nullable=False)

    menu_item: Mapped[MenuItem] = relationship("MenuItem", back_populates="ingredients")
    ingredient: Mapped[Ingredient] = relationship("Ingredient", back_populates="menu_links")

    def __repr__(self) -> str:
        return (
            f"<MenuItemIngredient menu_item={self.menu_item_id} "
            f"ingredient={self.ingredient_id} qty={self.quantity}>"
        )


class MenuOptionGroup(Base):
    __tablename__ = "menu_option_groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    menu_item_id: Mapped[int] = mapped_column(ForeignKey("menu_items.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    selection_type: Mapped[str] = mapped_column(String(20), default="single", nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    menu_item: Mapped[MenuItem] = relationship("MenuItem", back_populates="option_groups")
    options: Mapped[List["MenuOption"]] = relationship(
        "MenuOption",
        back_populates="group",
        cascade="all, delete-orphan",
        order_by="MenuOption.position",
    )

    def __repr__(self) -> str:
        return f"<MenuOptionGroup menu_item={self.menu_item_id} name={self.name}>"


class MenuOption(Base):
    __tablename__ = "menu_options"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("menu_option_groups.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    price_delta: Mapped[float] = mapped_column(Numeric(10, 2), default=0, nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    group: Mapped[MenuOptionGroup] = relationship("MenuOptionGroup", back_populates="options")

    def __repr__(self) -> str:
        return f"<MenuOption group={self.group_id} name={self.name} price={self.price_delta}>"


class StockMovementTypeEnum(str, Enum):
    RESTOCK = "restock"
    USAGE = "usage"
    ADJUSTMENT = "adjustment"


class StockMovement(Base):
    __tablename__ = "stock_movements"

    id: Mapped[int] = mapped_column(primary_key=True)
    ingredient_id: Mapped[int] = mapped_column(
        ForeignKey("ingredients.id"), nullable=False
    )
    change: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    movement_type: Mapped[str] = mapped_column(String(20), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=datetime.utcnow, nullable=False
    )

    ingredient: Mapped[Ingredient] = relationship("Ingredient", back_populates="movements")

    def __repr__(self) -> str:
        return f"<StockMovement ingredient={self.ingredient_id} change={self.change}>"


class OrderStatusEnum(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    PAID = "paid"


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    table_id: Mapped[int] = mapped_column(ForeignKey("dining_tables.id"), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), default=OrderStatusEnum.PENDING.value, nullable=False
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=datetime.utcnow, nullable=False
    )
    discount_amount: Mapped[float] = mapped_column(Numeric(10, 2), default=0, nullable=False)
    service_charge: Mapped[float] = mapped_column(Numeric(10, 2), default=0, nullable=False)
    tax_rate: Mapped[float] = mapped_column(Numeric(5, 2), default=0, nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)

    table: Mapped[DiningTable] = relationship("DiningTable", back_populates="orders")
    items: Mapped[List["OrderItem"]] = relationship(
        "OrderItem", back_populates="order", cascade="all, delete-orphan"
    )
    payments: Mapped[List["Payment"]] = relationship(
        "Payment",
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="Payment.paid_at",
    )
    invoice: Mapped["Invoice"] = relationship(
        "Invoice",
        back_populates="order",
        cascade="all, delete-orphan",
        uselist=False,
    )

    @property
    def subtotal(self) -> float:
        return float(sum((item.subtotal for item in self.items), 0.0))

    @property
    def discount(self) -> float:
        return float(self.discount_amount or 0)

    @property
    def service(self) -> float:
        return float(self.service_charge or 0)

    @property
    def tax_percentage(self) -> float:
        return float(self.tax_rate or 0)

    @property
    def tax_amount(self) -> float:
        taxable = max(self.subtotal - self.discount + self.service, 0.0)
        return round(taxable * (self.tax_percentage / 100), 2)

    @property
    def total(self) -> float:
        return self.grand_total

    @property
    def grand_total(self) -> float:
        return round(self.subtotal - self.discount + self.service + self.tax_amount, 2)

    @property
    def amount_paid(self) -> float:
        return float(sum((float(payment.amount) for payment in self.payments), 0.0))

    @property
    def balance_due(self) -> float:
        return round(self.grand_total - self.amount_paid, 2)

    @property
    def is_paid(self) -> bool:
        return self.balance_due <= 0.0 and bool(self.payments)

    def __repr__(self) -> str:
        return f"<Order #{self.id} table={self.table.code}>"


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    menu_item_id: Mapped[int] = mapped_column(ForeignKey("menu_items.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit_price: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)

    order: Mapped[Order] = relationship("Order", back_populates="items")
    menu_item: Mapped[MenuItem] = relationship("MenuItem", back_populates="order_items")

    @property
    def subtotal(self) -> float:
        price = self.unit_price if self.unit_price is not None else self.menu_item.price
        return float(price) * self.quantity


class PaymentMethodEnum(str, Enum):
    CASH = "cash"
    PROMPTPAY = "promptpay"
    CARD = "card"
    TRANSFER = "transfer"


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id"), nullable=False, unique=False
    )
    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    method: Mapped[str] = mapped_column(String(20), default=PaymentMethodEnum.CASH.value, nullable=False)
    reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    paid_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=datetime.utcnow, nullable=False
    )

    order: Mapped[Order] = relationship("Order", back_populates="payments")

    @property
    def amount_value(self) -> float:
        return float(self.amount or 0)


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False, unique=True)
    total_amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    net_amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    tax_amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    tax_rate: Mapped[float] = mapped_column(Numeric(5, 2), default=7.00, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=datetime.utcnow, nullable=False)

    order: Mapped[Order] = relationship("Order", back_populates="invoice")

    def __repr__(self) -> str:
        return f"<Invoice order={self.order_id} total={self.total_amount}>"


DEFAULT_TABLES = [
    {"name": "โต๊ะ 1", "code": "T1", "access_token": "0549ac5092a18311c0f2897480c6cdc5"},
    {"name": "โต๊ะ 2", "code": "T2", "access_token": "b3bd667e37b09a43840de0d2cd22decd"},
    {"name": "โต๊ะ 3", "code": "T3", "access_token": "acc445d237fc414be7bc47801129fc27"},
    {"name": "โต๊ะ 4", "code": "T4", "access_token": "38ad0f87570f53a65198eae755f1e358"},
    {"name": "โต๊ะ 5", "code": "T5", "access_token": "d2e7d6096120ef12b1d7249fbc4fc097"},
    {"name": "โต๊ะ 6", "code": "T6", "access_token": "ffca7b816578a2af2944cf12394341a2"},
    {"name": "โต๊ะ 7", "code": "T7", "access_token": "2310a43c49780625eebba06c05810250"},
]

DEFAULT_MENU_CATEGORIES = [
    {
        "name": "ก๋วยเตี๋ยว",
        "position": 1,
        "items": [
            {
                "name": "ก๋วยเตี๋ยวต้มยำสุโขทัยสูตรดั้งเดิม (แบบน้ำ)",
                "description": "น้ำซุปกลมกล่อมตำยำ ปรุงรสครบเครื่อง เสิร์ฟพร้อมหมูแดง หมูสับ กากหมู และถั่วฝักยาว",
                "price": 50.0,
                "position": 1,
                "image_path": "uploads/menu/97698.png",
                "allow_special": True,
                "special_price_delta": 10.0,
            },
            {
                "name": "ก๋วยเตี๋ยวต้มยำสุโขทัยสูตรดั้งเดิม (แบบแห้ง)",
                "description": "คลุกซอสตำยำสูตรโบราณ หอมมะนาวคั้นสด กินคู่ผักสดและกากหมูกรอบ",
                "price": 50.0,
                "position": 2,
                "image_path": "uploads/menu/97697.png",
                "allow_special": True,
                "special_price_delta": 10.0,
            },
        ],
    },
    {
        "name": "เกาเหลา",
        "position": 3,
        "items": [
            {
                "name": "เกาเหลา ต้มยำสุโขทัย",
                "price": 50.0,
                "position": 1,
                "image_path": "uploads/menu/noodle_soup.svg",
                "allow_special": True,
                "special_price_delta": 10.0,
            }
        ],
    },
    {
        "name": "ของทานเล่น",
        "position": 4,
        "items": [
            {
                "name": "ลูกชิ้นปิ้ง หมู",
                "price": 35.0,
                "position": 1,
                "image_path": "uploads/menu/1122148.jpg",
            },
            {
                "name": "ลูกชิ้นปิ้ง เนื้อ",
                "price": 35.0,
                "position": 2,
                "image_path": "uploads/menu/1122148.jpg",
            },
            {
                "name": "แคปหมู",
                "price": 19.0,
                "position": 3,
                "image_path": "uploads/menu/snack_pork_crackling.svg",
            },
            {
                "name": "เกี๊ยวกรอบ",
                "price": 19.0,
                "position": 4,
                "image_path": "uploads/menu/9920.png",
            },
        ],
    },
    {
        "name": "เครื่องดื่ม",
        "position": 5,
        "items": [
            {
                "name": "น้ำเปล่า",
                "price": 10.0,
                "position": 1,
                "image_path": "uploads/menu/9925.png",
            },
            {
                "name": "น้ำอัดลม ขวด",
                "price": 10.0,
                "position": 2,
                "image_path": "uploads/menu/9926.png",
            },
            {
                "name": "น้ำอัดลม กระป๋อง",
                "price": 20.0,
                "position": 3,
                "image_path": "uploads/menu/9923.png",
            },
            {
                "name": "น้ำสมุนไพร",
                "price": 15.0,
                "position": 4,
                "image_path": "uploads/menu/9927.png",
            },
        ],
    },
]

DEFAULT_MENU_OPTION_GROUPS = [
    {
        "menu_names": [
            "ก๋วยเตี๋ยวต้มยำสุโขทัยสูตรดั้งเดิม (แบบน้ำ)",
            "ก๋วยเตี๋ยวต้มยำสุโขทัยสูตรดั้งเดิม (แบบแห้ง)",
        ],
        "groups": [
            {
                "name": "กินที่ร้านหรือกลับบ้าน",
                "selection_type": "single",
                "is_required": True,
                "position": 1,
                "options": [
                    {"name": "กินที่ร้าน", "price_delta": 0.0, "position": 1},
                    {"name": "กลับบ้าน", "price_delta": 0.0, "position": 2},
                ],
            },
            {
                "name": "เลือกประเภทเส้น",
                "selection_type": "single",
                "is_required": True,
                "position": 2,
                "options": [
                    {"name": "เส้นเล็ก", "price_delta": 0.0, "position": 1},
                    {"name": "เส้นใหญ่", "price_delta": 0.0, "position": 2},
                    {"name": "หมี่ขาว", "price_delta": 0.0, "position": 3},
                    {"name": "เส้นหมี่เหลือง", "price_delta": 0.0, "position": 4},
                    {"name": "วุ้นเส้น", "price_delta": 0.0, "position": 5},
                    {"name": "มาม่า", "price_delta": 0.0, "position": 6},
                ],
            },
            {
                "name": "เพิ่มวัตถุดิบ",
                "selection_type": "multiple",
                "is_required": False,
                "position": 3,
                "options": [
                    {"name": "เพิ่มหมูแดง", "price_delta": 10.0, "position": 1},
                    {"name": "เพิ่มหมูสับ", "price_delta": 10.0, "position": 2},
                    {"name": "เพิ่มเกี๊ยว", "price_delta": 10.0, "position": 3},
                ],
            },
        ],
    },
    {
        "menu_names": ["น้ำอัดลม ขวด", "น้ำสมุนไพร"],
        "groups": [
            {
                "name": "สมุนไพร",
                "selection_type": "single",
                "is_required": True,
                "position": 1,
                "options": [
                    {"name": "ตะไคร้", "price_delta": 0.0, "position": 1},
                    {"name": "กระเจี๊ยบ", "price_delta": 0.0, "position": 2},
                    {"name": "เก๊กฮวย", "price_delta": 0.0, "position": 3},
                    {"name": "โอเลี้ยง", "price_delta": 0.0, "position": 4},
                    {"name": "ชาดำเย็น", "price_delta": 0.0, "position": 5},
                ],
            }
        ],
    },
]


def _ensure_default_option_groups() -> None:
    """Ensure default option groups & options exist for configured menu items."""
    if not DEFAULT_MENU_OPTION_GROUPS:
        return

    menu_items = db_session.query(MenuItem).all()
    menu_map = {item.name: item for item in menu_items}

    for entry in DEFAULT_MENU_OPTION_GROUPS:
        menu_names = entry.get("menu_names") or []
        groups_spec = entry.get("groups") or []
        for menu_name in menu_names:
            menu_item = menu_map.get(menu_name)
            if not menu_item:
                continue
            existing_groups = {group.name: group for group in menu_item.option_groups}
            for group_spec in groups_spec:
                group_name = group_spec.get("name")
                if not group_name:
                    continue
                group = existing_groups.get(group_name)
                if not group:
                    group = MenuOptionGroup(
                        menu_item=menu_item,
                        name=group_name,
                        selection_type=group_spec.get("selection_type", "single"),
                        is_required=group_spec.get("is_required", False),
                        position=group_spec.get("position", 0),
                    )
                    db_session.add(group)
                    db_session.flush()
                    existing_groups[group_name] = group
                else:
                    group.selection_type = group_spec.get("selection_type", group.selection_type)
                    group.is_required = group_spec.get("is_required", group.is_required)
                    group.position = group_spec.get("position", group.position)

                existing_options = {option.name: option for option in group.options}
                for idx, option_spec in enumerate(group_spec.get("options") or [], start=1):
                    option_name = option_spec.get("name")
                    if not option_name:
                        continue
                    option = existing_options.get(option_name)
                    if not option:
                        option = MenuOption(
                            group=group,
                            name=option_name,
                            price_delta=option_spec.get("price_delta", 0.0),
                            position=option_spec.get("position", idx),
                        )
                        db_session.add(option)
                        existing_options[option_name] = option
                    else:
                        option.price_delta = option_spec.get("price_delta", option.price_delta)
                        option.position = option_spec.get("position", option.position or idx)


def seed_sample_data(force: bool = False) -> None:
    """Populate the database with sample tables and menu items."""
    if force:
        db_session.query(Payment).delete(synchronize_session=False)
        db_session.query(OrderItem).delete(synchronize_session=False)
        db_session.query(Order).delete(synchronize_session=False)
        db_session.query(StockMovement).delete(synchronize_session=False)
        db_session.query(MenuItemIngredient).delete(synchronize_session=False)
        db_session.query(MenuItem).delete(synchronize_session=False)
        db_session.query(MenuCategory).delete(synchronize_session=False)
        db_session.query(Ingredient).delete(synchronize_session=False)
        db_session.query(DiningTable).delete(synchronize_session=False)
        db_session.commit()

    if db_session.query(DiningTable).count() == 0:
        tables = [
            DiningTable(
                name=table["name"],
                code=table["code"],
                access_token=table.get("access_token"),
            )
            for table in DEFAULT_TABLES
        ]
        db_session.add_all(tables)

    if db_session.query(MenuCategory).count() == 0:
        for category_spec in DEFAULT_MENU_CATEGORIES:
            category = MenuCategory(
                name=category_spec["name"],
                position=category_spec.get("position", 0),
            )
            db_session.add(category)
            db_session.flush()
            items = category_spec.get("items", [])
            for idx, item_spec in enumerate(items, start=1):
                db_session.add(
                    MenuItem(
                        name=item_spec["name"],
                        description=item_spec.get("description"),
                        price=item_spec["price"],
                        category=category,
                        position=item_spec.get("position", idx),
                        image_path=item_spec.get("image_path"),
                        allow_special=item_spec.get("allow_special", False),
                        special_price_delta=item_spec.get("special_price_delta", 0.0),
                    )
                )

    if db_session.query(Ingredient).count() == 0:
        ingredient_specs = [
            {"name": "เส้นก๋วยเตี๋ยว", "unit": "กำ", "quantity": 200, "reorder": 40},
            {"name": "น้ำซุป", "unit": "ลิตร", "quantity": 50, "reorder": 10},
            {"name": "หมูสไลซ์", "unit": "กิโลกรัม", "quantity": 20, "reorder": 5},
            {"name": "เนื้อสไลซ์", "unit": "กิโลกรัม", "quantity": 15, "reorder": 5},
            {"name": "เกี๊ยว", "unit": "ชิ้น", "quantity": 300, "reorder": 60},
            {"name": "ใบโหระพา", "unit": "กำ", "quantity": 80, "reorder": 20},
            {"name": "น้ำแข็ง", "unit": "กิโลกรัม", "quantity": 100, "reorder": 20},
            {"name": "ผงชา", "unit": "กิโลกรัม", "quantity": 5, "reorder": 1},
            {"name": "น้ำอัดลม (ขวด)", "unit": "ขวด", "quantity": 48, "reorder": 12},
        ]

        ingredients = []
        for spec in ingredient_specs:
            ingredient = Ingredient(
                name=spec["name"],
                unit=spec["unit"],
                quantity_on_hand=spec["quantity"],
                reorder_level=spec["reorder"],
            )
            ingredients.append(ingredient)
        db_session.add_all(ingredients)
        db_session.flush()

        for ingredient in ingredients:
            db_session.add(
                StockMovement(
                    ingredient=ingredient,
                    change=ingredient.quantity_on_hand,
                    movement_type=StockMovementTypeEnum.RESTOCK.value,
                    note="Initial stock",
                )
            )

    db_session.commit()

    if db_session.query(MenuItemIngredient).count() == 0:
        ingredients_map = {ing.name: ing for ing in db_session.query(Ingredient).all()}
        menu_map = {item.name: item for item in db_session.query(MenuItem).all()}

        mapping_specs = [
            ("ก๋วยเตี๋ยวตำยำสุโขทัยสูตรดั่งเดิม (แบบน้ำ)", "เส้นก๋วยเตี๋ยว", 1.0),
            ("ก๋วยเตี๋ยวตำยำสุโขทัยสูตรดั่งเดิม (แบบน้ำ)", "น้ำซุป", 0.6),
            ("ก๋วยเตี๋ยวตำยำสุโขทัยสูตรดั่งเดิม (แบบน้ำ)", "หมูสไลซ์", 0.25),
            ("ก๋วยเตี๋ยวตำยำสุโขทัยสูตรดั่งเดิม (แบบน้ำ)", "ใบโหระพา", 0.05),
            ("ก๋วยเตี๋ยวตำยำสุโขทัยสูตรดั่งเดิม (แบบแห้ง)", "เส้นก๋วยเตี๋ยว", 1.0),
            ("ก๋วยเตี๋ยวตำยำสุโขทัยสูตรดั่งเดิม (แบบแห้ง)", "หมูสไลซ์", 0.25),
            ("ก๋วยเตี๋ยวตำยำสุโขทัยสูตรดั่งเดิม (แบบแห้ง)", "ใบโหระพา", 0.05),
        ]

        for menu_name, ingredient_name, quantity in mapping_specs:
            menu_item = menu_map.get(menu_name)
            ingredient = ingredients_map.get(ingredient_name)
            if not menu_item or not ingredient:
                continue
            db_session.add(
                MenuItemIngredient(
                    menu_item=menu_item,
                    ingredient=ingredient,
                    quantity=quantity,
                )
            )

    db_session.commit()

    _ensure_default_option_groups()
    db_session.commit()
