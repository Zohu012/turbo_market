from datetime import datetime, date
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, Computed, ForeignKey, Index, Integer, Numeric,
    SmallInteger, String, Text, TIMESTAMP, Date, func
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
    hp: Mapped[Optional[int]] = mapped_column(SmallInteger)
    body_type: Mapped[Optional[str]] = mapped_column(String(80))
    transmission: Mapped[Optional[str]] = mapped_column(String(80))
    fuel_type: Mapped[Optional[str]] = mapped_column(String(80))
    drive_type: Mapped[Optional[str]] = mapped_column(String(80))
    doors: Mapped[Optional[int]] = mapped_column(SmallInteger)
    vin: Mapped[Optional[str]] = mapped_column(String(50))
    condition: Mapped[Optional[str]] = mapped_column(String(120))
    market_for: Mapped[Optional[str]] = mapped_column(String(80))
    description: Mapped[Optional[str]] = mapped_column(Text)

    # view_count is cumulative across relistings. view_count_base holds the sum
    # of all prior post lifetimes; last_scraped_view_count is the most recent
    # raw value from turbo.az (used to detect a reset on re-activation).
    view_count: Mapped[Optional[int]] = mapped_column(Integer)
    view_count_base: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_scraped_view_count: Mapped[Optional[int]] = mapped_column(Integer)

    is_on_order: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, Computed("status = 'active'", persisted=True))
    date_added: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    date_updated: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    date_updated_turbo: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    date_deactivated: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    last_activated_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))

    # days_to_sell is frozen at deactivation = active_days_accumulated +
    # (date_deactivated - last_activated_at). Accumulates across relistings.
    days_to_sell: Mapped[Optional[int]] = mapped_column(Integer)
    active_days_accumulated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Two-miss sold detection: bumped each full scan a listing is absent,
    # reset to 0 when it reappears. Deactivation only fires at >= 2.
    missing_scan_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Set to the current scrape session's started_at every time a listing card
    # is observed. A delist-suspect is any active vehicle whose last_seen_at
    # is older than the current session's start.
    last_seen_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    # Queue flag for the decoupled Listing → Details Update split. Set TRUE
    # by Listing runs on new / reactivated / bumped / delist-suspect rows;
    # cleared by Details Update after the row processes.
    needs_detail_refresh: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

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
    odometer_history: Mapped[list["OdometerHistory"]] = relationship(
        "OdometerHistory", back_populates="vehicle", cascade="all, delete-orphan",
        order_by="OdometerHistory.recorded_at.desc()"
    )
    view_count_history: Mapped[list["ViewCountHistory"]] = relationship(
        "ViewCountHistory", back_populates="vehicle", cascade="all, delete-orphan",
        order_by="ViewCountHistory.recorded_at.desc()"
    )
    features: Mapped[list["Feature"]] = relationship(
        "Feature", secondary="vehicle_features", back_populates="vehicles"
    )
    labels: Mapped[list["Label"]] = relationship(
        "Label", secondary="vehicle_labels", back_populates="vehicles"
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
        Index("idx_vehicles_date_updated_turbo", "date_updated_turbo"),
        Index("idx_vehicles_last_seen_at", "last_seen_at"),
        Index("idx_vehicles_make_model_year_status", "make", "model", "year", "status"),
        Index(
            "idx_vehicles_needs_detail_refresh",
            "needs_detail_refresh",
            postgresql_where="needs_detail_refresh = TRUE",
        ),
    )


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


class OdometerHistory(Base):
    __tablename__ = "odometer_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vehicle_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False
    )
    odometer: Mapped[int] = mapped_column(Integer, nullable=False)
    odometer_type: Mapped[Optional[str]] = mapped_column(String(5))
    recorded_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    vehicle: Mapped["Vehicle"] = relationship("Vehicle", back_populates="odometer_history")

    __table_args__ = (
        Index("idx_odo_history_vehicle_date", "vehicle_id", "recorded_at"),
    )


class ViewCountHistory(Base):
    __tablename__ = "view_count_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vehicle_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False
    )
    view_count: Mapped[int] = mapped_column(Integer, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    vehicle: Mapped["Vehicle"] = relationship("Vehicle", back_populates="view_count_history")

    __table_args__ = (
        Index("idx_viewc_history_vehicle_date", "vehicle_id", "recorded_at"),
    )


class Feature(Base):
    __tablename__ = "features"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)

    vehicles: Mapped[list["Vehicle"]] = relationship(
        "Vehicle", secondary="vehicle_features", back_populates="features"
    )


class VehicleFeature(Base):
    __tablename__ = "vehicle_features"

    vehicle_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vehicles.id", ondelete="CASCADE"), primary_key=True
    )
    feature_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("features.id", ondelete="CASCADE"), primary_key=True
    )

    __table_args__ = (
        Index("idx_vehicle_features_feature", "feature_id"),
    )


class Label(Base):
    __tablename__ = "labels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)

    vehicles: Mapped[list["Vehicle"]] = relationship(
        "Vehicle", secondary="vehicle_labels", back_populates="labels"
    )


class VehicleLabel(Base):
    __tablename__ = "vehicle_labels"

    vehicle_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vehicles.id", ondelete="CASCADE"), primary_key=True
    )
    label_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("labels.id", ondelete="CASCADE"), primary_key=True
    )
