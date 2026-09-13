from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

MIN_LEN = 1
MAX_LEN = 100000
MIN_ALLOWANCE = 0
MAX_ALLOWANCE = 10000
MAX_SEGMENTS = 12
ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$"
# Optional kit (套组) markers use the same shape as segment ids.
KIT_PATTERN = ID_PATTERN


class SegmentIn(BaseModel):
    id: str = Field(pattern=ID_PATTERN)
    # Measurements arrive as JSON numbers; StrictInt rejects booleans,
    # numeric strings and floats (including 10.0) instead of coercing them.
    length: StrictInt = Field(ge=MIN_LEN, le=MAX_LEN)
    # Optional end-trim allowance; omitted means 0 (legacy clients).
    allowance: StrictInt = Field(default=0, ge=MIN_ALLOWANCE, le=MAX_ALLOWANCE)
    # Optional kit id: segments sharing one kit id are kept on a single roll.
    # Omitted/null means an independent segment, packed exactly as before.
    # A blank string is treated as "left unfilled" and normalized to None.
    kit_id: str | None = Field(default=None, pattern=KIT_PATTERN)

    @field_validator("kit_id", mode="before")
    @classmethod
    def _blank_kit_is_none(cls, value):
        if isinstance(value, str) and value.strip() == "":
            return None
        return value


class PlanCreate(BaseModel):
    roll_length: StrictInt = Field(ge=MIN_LEN, le=MAX_LEN)
    kerf_width: StrictInt = Field(ge=MIN_LEN, le=MAX_LEN)
    segments: list[SegmentIn] = Field(min_length=1, max_length=MAX_SEGMENTS)
    # Optional provenance: when present it must reference an existing plan.
    # It never participates in solving; omitted means an ordinary new plan.
    # StrictInt keeps `true` from aliasing plan 1 (bool is an int subclass).
    source_plan_id: StrictInt | None = Field(default=None, ge=1)


class SegmentOut(BaseModel):
    id: str
    length: int
    allowance: int
    # Kit marker echoed back alongside the cut; None for independent segments
    # and for every historical cut.
    kit_id: str | None = None
    # None while the segment is waiting to be cut; old plans keep None.
    completed_at: datetime | None = None


class RollOut(BaseModel):
    position: int
    segments: list[SegmentOut]
    kerf_count: int
    used_length: int
    leftover: int
    completed_count: int = 0


class PlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    roll_length: int
    kerf_width: int
    rolls_used: int
    total_kerf_count: int
    total_leftover: int
    completed_segment_count: int = 0
    created_at: datetime
    source_plan_id: int | None = None
    rolls: list[RollOut]


class CutAction(BaseModel):
    # The cut position (1-based, canonical order) the page believes it is
    # acting on. The server rejects anything other than the true next/last
    # position with 409 so stale pages cannot advance progress blindly.
    position: int = Field(ge=1)


class PlanSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    roll_length: int
    kerf_width: int
    segment_count: int
    rolls_used: int
    total_kerf_count: int
    total_leftover: int
    created_at: datetime
    source_plan_id: int | None = None


# --- material review sheets (用料复核单) -------------------------------------

# A measured leftover can never exceed the largest roll, and the uniform
# tolerance uses the same ceiling as the segment allowance.
MAX_MEASURED = MAX_LEN
MAX_TOLERANCE = MAX_ALLOWANCE


class ReviewMeasurementIn(BaseModel):
    # Canonical roll position (1-based) being measured; StrictInt keeps
    # booleans, numeric strings and floats from being coerced.
    roll_position: StrictInt = Field(ge=1)
    measured_leftover: StrictInt = Field(ge=0, le=MAX_MEASURED)


class ReviewSheetCreate(BaseModel):
    plan_id: StrictInt = Field(ge=1)
    # Uniform allowed deviation applied to every roll of the batch.
    tolerance_mm: StrictInt = Field(ge=0, le=MAX_TOLERANCE)
    # One row per roll of the plan; coverage/duplicates are checked against
    # the plan itself in the endpoint so errors can point at the exact row.
    measurements: list[ReviewMeasurementIn] = Field(
        min_length=1, max_length=MAX_SEGMENTS
    )


class ReviewMeasurementOut(BaseModel):
    roll_position: int
    theoretical_leftover: int
    measured_leftover: int
    deviation: int
    ok: bool


class ReviewSheetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    plan_id: int
    tolerance_mm: int
    batch_ok: bool
    created_at: datetime
    measurements: list[ReviewMeasurementOut]
