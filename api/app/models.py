from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import relationship

from .db import Base


class Plan(Base):
    __tablename__ = "plans"

    id = Column(Integer, primary_key=True)
    roll_length = Column(Integer, nullable=False)
    kerf_width = Column(Integer, nullable=False)
    segment_count = Column(Integer, nullable=False)
    rolls_used = Column(Integer, nullable=False)
    total_kerf_count = Column(Integer, nullable=False)
    total_leftover = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Nullable link to the plan this one was adjusted from. Never read by the
    # solver; it is provenance only. ON DELETE SET NULL keeps every plan
    # reachable on its own even if the source plan is later removed.
    source_plan_id = Column(
        Integer,
        ForeignKey("plans.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    rolls = relationship(
        "Roll",
        back_populates="plan",
        order_by="Roll.position",
        cascade="all, delete-orphan",
    )


class Roll(Base):
    __tablename__ = "rolls"

    id = Column(Integer, primary_key=True)
    plan_id = Column(
        Integer, ForeignKey("plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position = Column(Integer, nullable=False)  # 1-based, canonical order
    kerf_count = Column(Integer, nullable=False)
    used_length = Column(Integer, nullable=False)
    leftover = Column(Integer, nullable=False)

    plan = relationship("Plan", back_populates="rolls")
    cuts = relationship(
        "Cut",
        back_populates="roll",
        order_by="Cut.position",
        cascade="all, delete-orphan",
    )


class Cut(Base):
    __tablename__ = "cuts"

    id = Column(Integer, primary_key=True)
    roll_id = Column(
        Integer, ForeignKey("rolls.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position = Column(Integer, nullable=False)  # 1-based cutting order
    segment_id = Column(String(32), nullable=False)
    length = Column(Integer, nullable=False)  # delivered length
    allowance = Column(Integer, nullable=False, default=0)  # end-trim allowance
    # Optional kit (套组) marker: cuts sharing a value were kept on one roll.
    # NULL for independent segments and for every historical cut.
    kit_id = Column(String(32), nullable=True)
    # Null while the segment is still waiting to be cut; set when the
    # foreman records "complete this segment". Historical rows stay NULL.
    completed_at = Column(DateTime(timezone=True), nullable=True)

    roll = relationship("Roll", back_populates="cuts")


class ReviewSheet(Base):
    """用料复核单: after a batch is cut, the foreman measures the actual
    leftover of every roll and records one review sheet against the plan.

    The sheet stores the uniform tolerance plus the computed batch verdict;
    each roll's measurement (with its computed deviation and verdict) lives
    in ``review_measurements``. A plan gets at most one sheet (unique
    ``plan_id``); creating a sheet never rewrites the plan, its cuts or the
    cutting progress.
    """

    __tablename__ = "review_sheets"

    id = Column(Integer, primary_key=True)
    plan_id = Column(
        Integer,
        ForeignKey("plans.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    # Uniform allowed deviation (mm) shared by every roll of the batch.
    tolerance_mm = Column(Integer, nullable=False)
    # Whole-batch verdict: True when every roll's deviation is within the
    # tolerance. Stored so a refetch never recomputes against a changed plan.
    batch_ok = Column(Boolean, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    plan = relationship("Plan")
    measurements = relationship(
        "ReviewMeasurement",
        back_populates="sheet",
        order_by="ReviewMeasurement.roll_position",
        cascade="all, delete-orphan",
    )


class ReviewMeasurement(Base):
    """One roll's measured leftover plus the computed review results."""

    __tablename__ = "review_measurements"

    id = Column(Integer, primary_key=True)
    sheet_id = Column(
        Integer,
        ForeignKey("review_sheets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    roll_position = Column(Integer, nullable=False)  # canonical roll order, 1-based
    # Baseline copied from the plan roll at creation time.
    theoretical_leftover = Column(Integer, nullable=False)
    measured_leftover = Column(Integer, nullable=False)
    # abs(measured - theoretical), stored with the sheet.
    deviation = Column(Integer, nullable=False)
    # Per-roll verdict: deviation <= tolerance.
    ok = Column(Boolean, nullable=False)

    sheet = relationship("ReviewSheet", back_populates="measurements")
