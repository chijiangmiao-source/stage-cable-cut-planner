from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .db import Base, SessionLocal, engine, run_migrations
from .models import Cut, Plan, Roll
from .schemas import PlanCreate, PlanOut, PlanSummary, RollOut, SegmentOut
from .solver import Segment, solve


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    run_migrations()
    yield


app = FastAPI(title="Roll Cutting Planner", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _err(loc: list, msg: str) -> dict:
    return {"loc": loc, "msg": msg, "type": "value_error"}


def _plan_to_out(plan: Plan) -> PlanOut:
    return PlanOut(
        id=plan.id,
        roll_length=plan.roll_length,
        kerf_width=plan.kerf_width,
        rolls_used=plan.rolls_used,
        total_kerf_count=plan.total_kerf_count,
        total_leftover=plan.total_leftover,
        created_at=plan.created_at,
        source_plan_id=plan.source_plan_id,
        rolls=[
            RollOut(
                position=roll.position,
                segments=[SegmentOut(id=c.segment_id, length=c.length) for c in roll.cuts],
                kerf_count=roll.kerf_count,
                used_length=roll.used_length,
                leftover=roll.leftover,
            )
            for roll in plan.rolls
        ],
    )


@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.post("/api/plans", response_model=PlanOut, status_code=201)
def create_plan(payload: PlanCreate, db: Session = Depends(get_db)):
    # Cross-field validation. Every error points at the exact field/segment
    # and nothing is persisted when any error is found.
    errors: list[dict] = []
    seen: dict[str, int] = {}
    for i, seg in enumerate(payload.segments):
        if seg.id in seen:
            errors.append(
                _err(["segments", i, "id"], f"duplicate segment id {seg.id!r}")
            )
        else:
            seen[seg.id] = i
        if seg.length > payload.roll_length:
            errors.append(
                _err(
                    ["segments", i, "length"],
                    f"segment length {seg.length} exceeds usable roll length "
                    f"{payload.roll_length}",
                )
            )

    # Provenance check: an adjustment request must name an existing plan.
    # A missing source is a field-level 422 (the form keeps all edits and
    # prompts to re-pick), never a dangling link or a half-written record.
    if payload.source_plan_id is not None:
        source_exists = db.scalar(
            select(Plan.id).where(Plan.id == payload.source_plan_id)
        )
        if source_exists is None:
            errors.append(
                _err(
                    ["source_plan_id"],
                    f"source plan {payload.source_plan_id} not found",
                )
            )

    if errors:
        raise HTTPException(status_code=422, detail=errors)

    solution = solve(
        payload.roll_length,
        payload.kerf_width,
        [Segment(s.id, s.length) for s in payload.segments],
    )

    plan = Plan(
        roll_length=payload.roll_length,
        kerf_width=payload.kerf_width,
        segment_count=len(payload.segments),
        rolls_used=solution.rolls_used,
        total_kerf_count=solution.total_kerf_count,
        total_leftover=solution.total_leftover,
        source_plan_id=payload.source_plan_id,
    )
    for pos, roll in enumerate(solution.rolls, start=1):
        db_roll = Roll(
            position=pos,
            kerf_count=roll.kerf_count,
            used_length=roll.used_length,
            leftover=roll.leftover,
        )
        for cut_pos, (sid, length) in enumerate(
            zip(roll.segment_ids, roll.lengths), start=1
        ):
            db_roll.cuts.append(Cut(position=cut_pos, segment_id=sid, length=length))
        plan.rolls.append(db_roll)

    db.add(plan)
    db.commit()
    db.refresh(plan)
    return _plan_to_out(plan)


@app.get("/api/plans", response_model=list[PlanSummary])
def list_plans(db: Session = Depends(get_db)):
    return db.scalars(select(Plan).order_by(Plan.id.desc())).all()


@app.get("/api/plans/{plan_id}", response_model=PlanOut)
def get_plan(plan_id: int, db: Session = Depends(get_db)):
    plan = db.get(Plan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="plan not found")
    return _plan_to_out(plan)
