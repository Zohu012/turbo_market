from datetime import datetime, date
from typing import Optional, TYPE_CHECKING

from sqlalchemy import BigInteger, Date, ForeignKey, Index, Numeric, String, TIMESTAMP, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.vehicle import Vehicle


class Seller(Base):
    __tablename__ = "sellers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    turbo_seller_id: Mapped[Optional[str]] = mapped_column(String(100), unique=True)
    name: Mapped[Optional[str]] = mapped_column(String(255))
    # 'business' = has /avtosalonlar/ shop page
    # 'dealer'   = no shop page, but >1 lifetime listing
    # 'private'  = everyone else
    seller_type: Mapped[Optional[str]] = mapped_column(String(20))
    city: Mapped[Optional[str]] = mapped_column(String(100))
    address: Mapped[Optional[str]] = mapped_column(String(500))
    profile_url: Mapped[Optional[str]] = mapped_column(String(500))
    regdate: Mapped[Optional[date]] = mapped_column(Date)
    first_seen: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    total_listings: Mapped[int] = mapped_column(BigInteger, default=0)
    total_sold: Mapped[int] = mapped_column(BigInteger, default=0)
    avg_days_to_sell: Mapped[Optional[float]] = mapped_column(Numeric(6, 1))

    phones: Mapped[list["SellerPhone"]] = relationship(
        "SellerPhone", back_populates="seller", cascade="all, delete-orphan"
    )
    vehicles: Mapped[list["Vehicle"]] = relationship("Vehicle", back_populates="seller")


class SellerPhone(Base):
    __tablename__ = "seller_phones"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    seller_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sellers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    phone: Mapped[str] = mapped_column(String(50), nullable=False)
    normalized: Mapped[str] = mapped_column(String(30), nullable=False)

    seller: Mapped["Seller"] = relationship("Seller", back_populates="phones")

    __table_args__ = (
        Index("idx_seller_phones_normalized", "normalized", unique=True),
    )
