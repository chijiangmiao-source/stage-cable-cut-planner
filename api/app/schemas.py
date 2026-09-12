from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

MIN_LEN = 1
MAX_LEN = 100000
MAX_SEGMENTS = 12
ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$"


class SegmentIn(BaseModel):
    id: str = Field(pattern=ID_PATTERN)
    length: int = Field(ge=MIN_LEN, le=MAX_LEN)


class PlanCreate(BaseModel):
    roll_length: int = Field(ge=MIN_LEN, le=MAX_LEN)
    kerf_width: int = Field(ge=MIN_LEN, le=MAX_LEN)
    segments: list[SegmentIn] = Field(min_length=1, max_length=MAX_SEGMENTS)


class SegmentOut(BaseModel):
    id: str
    length: int


class RollOut(BaseModel):
    position: int
    segments: list[SegmentOut]
    kerf_count: int
    used_length: int
    leftover: int


class PlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    roll_length: int
    kerf_width: int
    rolls_used: int
    total_kerf_count: int
    total_leftover: int
    created_at: datetime
    rolls: list[RollOut]


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
