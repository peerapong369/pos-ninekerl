from sqlalchemy import create_engine, text
from sqlalchemy.orm import scoped_session, sessionmaker, DeclarativeBase


class Base(DeclarativeBase):
    pass


engine = None
db_session = scoped_session(sessionmaker())


def init_db(database_uri: str) -> None:
    global engine
    engine = create_engine(database_uri, echo=False, future=True)
    db_session.configure(bind=engine)

    # Import models to ensure metadata is ready before create_all
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _upgrade_schema(engine)


def _upgrade_schema(engine) -> None:
    """Apply lightweight schema upgrades for existing SQLite databases."""
    if engine.dialect.name != "sqlite":
        return

    with engine.begin() as connection:
        orders_columns = {
            row["name"]
            for row in connection.execute(text("PRAGMA table_info('orders')")).mappings()
        }

        if "discount_amount" not in orders_columns:
            connection.execute(
                text(
                    "ALTER TABLE orders ADD COLUMN discount_amount NUMERIC(10,2) "
                    "NOT NULL DEFAULT 0"
                )
            )

        if "service_charge" not in orders_columns:
            connection.execute(
                text(
                    "ALTER TABLE orders ADD COLUMN service_charge NUMERIC(10,2) "
                    "NOT NULL DEFAULT 0"
                )
            )

        if "tax_rate" not in orders_columns:
            connection.execute(
                text(
                    "ALTER TABLE orders ADD COLUMN tax_rate NUMERIC(5,2) "
                    "NOT NULL DEFAULT 0"
                )
            )

        if "paid_at" not in orders_columns:
            connection.execute(
                text("ALTER TABLE orders ADD COLUMN paid_at DATETIME NULL")
            )

        order_item_columns = {
            row["name"]
            for row in connection.execute(text("PRAGMA table_info('order_items')")).mappings()
        }

        if "unit_price" not in order_item_columns:
            connection.execute(
                text("ALTER TABLE order_items ADD COLUMN unit_price NUMERIC(10,2) NULL")
            )

        menu_item_columns = {
            row["name"]
            for row in connection.execute(text("PRAGMA table_info('menu_items')")).mappings()
        }

        if "image_path" not in menu_item_columns:
            connection.execute(
                text("ALTER TABLE menu_items ADD COLUMN image_path VARCHAR(255) NULL")
            )

        if "allow_special" not in menu_item_columns:
            connection.execute(
                text("ALTER TABLE menu_items ADD COLUMN allow_special BOOLEAN NOT NULL DEFAULT 0")
            )

        if "special_price_delta" not in menu_item_columns:
            connection.execute(
                text(
                    "ALTER TABLE menu_items ADD COLUMN special_price_delta NUMERIC(10,2) NOT NULL DEFAULT 0"
                )
            )

        table_columns = {
            row["name"]
            for row in connection.execute(text("PRAGMA table_info('dining_tables')")).mappings()
        }

        if "access_token" not in table_columns:
            connection.execute(
                text("ALTER TABLE dining_tables ADD COLUMN access_token VARCHAR(64) NULL")
            )
