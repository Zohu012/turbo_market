from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, ForeignKey, Index, Integer, Numeric,
    SmallInteger, String, Text, TIMESTAMP, func, case, extract
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    turbo_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False, index=True)

    make: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(150), nullable=False)
    year: Mapped[Optional[int]] = mapped_column(SmallInteger)
    price: Mapped[Optional[int]] = mapped_column(Integer)
    currency: Mapped[Optional[str]] = mapped_column(String(3))
    price_azn: Mapped[Optional[float]] = mapped_column(Numeric(12, 2))

    odometer: Mapped[Optional[int]] = mapped_column(Integer)
    odometer_type: Mapped[Optional[str]] = mapped_column(String(5))
    color: Mapped[Optional[str]] = mapped_column(String(80))
    engine: Mapped[Optional[str]] = mapped_column(String(100))
    body_type: Mapped[Optional[str]] = mapped_column(String(80))
    transmission: Mapped[Optional[str]] = mapped_column(String(80))
    fuel_type: Mapped[Optional[str]] = mapped_column(String(80))
    drive_type: Mapped[Optional[str]] = mapped_column(String(80))
    doors: Mapped[Optional[int]] = mapped_column(SmallInteger)
    vin: Mapped[Optional[str]] = mapped_column(String(50))
    description: Mapped[Optional[str]] = mapped_column(Text)
    view_count: Mapped[Optional[int]] = mapped_column(Integer)
    url: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)
    date_added: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    date_updated: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    date_deactivated: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))

    seller_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("sellers.id", ondelete="SET NULL")
    )
    city: Mapped[Optional[str]] = mapped_column(String(100))
    raw_detail_json: Mapped[Optional[dict]] = mapped_column(JSONB)

    # relationships
    images: Mapped[list["VehicleImage"]] = relationship(
        "VehicleImage", back_populates="vehicle", cascade="all, delete-orphan",
        order_by="VehicleImage.position"
    )
    price_history: Mapped[list["PriceHistory"]] = relationship(
        "PriceHistory", back_populates="vehicle", cascade="all, delete-orphan",
        order_by="PriceHistory.recorded_at.desc()"
    )
    seller: Mapped[Optional["Seller"]] = relationship("Seller", back_populates="vehicles")

    __table_args__ = (
        Index("idx_vehicles_make", "make"),
        Index("idx_vehicles_make_model", "make", "model"),
        Index("idx_vehicles_year", "year"),
        Index("idx_vehicles_price_azn", "price_azn"),
        Index("idx_vehicles_odometer", "odometer"),
        Index("idx_vehicles_color", "color"),
        Index("idx_vehicles_fuel_type", "fuel_type"),
        Index("idx_vehicles_transmission", "transmission"),
        Index("idx_vehicles_seller_id", "seller_id"),
        Index("idx_vehicles_date_added", "date_added"),
        Index("idx_vehicles_make_model_year_status", "make", "model", "year", "status"),
    )

    @property
    def days_to_sell(self) -> Optional[int]:
        if self.date_deactivated and self.date_added:
            return (self.date_deactivated - self.date_added).days
        return None


class VehicleImage(Base):
    __tablename__ = "vehicle_images"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vehicle_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(SmallInteger, default=0)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)

    vehicle: Mapped["Vehicle"] = relationship("Vehicle", back_populates="images")


class PriceHistory(Base):
    __tablename__ = "price_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vehicle_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False
    )
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    price_azn: Mapped[Optional[float]] = mapped_column(Numeric(12, 2))
    recorded_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    vehicle: Mapped["Vehicle"] = relationship("Vehicle", back_populates="price_history")

    __table_args__ = (
        Index("idx_price_history_vehicle_date", "vehicle_id", "recorded_at"),
    )
