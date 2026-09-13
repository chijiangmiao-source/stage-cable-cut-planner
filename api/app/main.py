from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db import Base, SessionLocal, engine, run_migrations
from .migrations import run_startup_migrations
from .models import Cut, Plan, ReviewMeasurement, ReviewSheet, Roll
from .schemas import (
    CutAction,
    PlanCreate,
    PlanOut,
    PlanSummary,
    ReviewMeasurementOut,
    ReviewSheetCreate,
    ReviewSheetOut,
    RollOut,
    SegmentOut,
)
from .solver import Segment, find_kit_errors, solve


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Fresh DBs build through the migration chain; legacy DBs are stamped at
    # the baseline first, so historical cuts stay unfinished.
    run_startup_migrations(engine)
    # Kept as a safety net for environments where migrations cannot run.
    Base.metadata.create_all(bind=engine)
    run_migrations()
    yield


app = FastAPI(title="Roll Cutting Planner", version="1.4.0", lifespan=lifespan)
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
    completed_total = 0
    rolls_out: list[RollOut] = []
    for roll in plan.rolls:
        segments: list[SegmentOut] = []
        completed_in_roll = 0
        for cut in roll.cuts:
            if cut.completed_at is not None:
                completed_in_roll += 1
            segments.append(
                SegmentOut(
                    id=cut.segment_id,
                    length=cut.length,
                    allowance=cut.allowance,
                    kit_id=cut.kit_id,
                    completed_at=cut.completed_at,
                )
            )
        completed_total += completed_in_roll
        rolls_out.append(
            RollOut(
                position=roll.position,
                segments=segments,
                kerf_count=roll.kerf_count,
                used_length=roll.used_length,
                leftover=roll.leftover,
                completed_count=completed_in_roll,
            )
        )
    return PlanOut(
        id=plan.id,
        roll_length=plan.roll_length,
        kerf_width=plan.kerf_width,
        rolls_used=plan.rolls_used,
        total_kerf_count=plan.total_kerf_count,
        total_leftover=plan.total_leftover,
        completed_segment_count=completed_total,
        created_at=plan.created_at,
        source_plan_id=plan.source_plan_id,
        rolls=rolls_out,
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
        elif seg.length + seg.allowance > payload.roll_length:
            # The delivered length alone fits; the allowance is what pushes
            # the actual cutting length past the roll, so blame that input.
            errors.append(
                _err(
                    ["segments", i, "allowance"],
                    f"segment length {seg.length} + allowance {seg.allowance} "
                    f"exceeds usable roll length {payload.roll_length}",
                )
            )

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

    # Kit feasibility is independent of the other field checks: a kit whose
    # members cannot share one roll is reported on every member row's kit
    # input, stating the overflow in millimetres. It is evaluated in the same
    # pass so a request can report an oversized segment and an infeasible kit
    # together.
    segments_for_solve = [
        Segment(s.id, s.length, s.allowance, s.kit_id) for s in payload.segments
    ]
    for kit_error in find_kit_errors(
        payload.roll_length, payload.kerf_width, segments_for_solve
    ):
        for i, seg in enumerate(payload.segments):
            if seg.kit_id != kit_error.kit_id:
                continue
            errors.append(
                _err(
                    ["segments", i, "kit_id"],
                    f"kit {kit_error.kit_id!r} cannot fit on one roll: its cut "
                    f"lengths plus internal kerfs total {kit_error.used_length} "
                    f"mm, exceeding usable roll length {payload.roll_length} "
                    f"by {kit_error.overflow_mm} mm",
                )
            )

    if errors:
        raise HTTPException(status_code=422, detail=errors)

    solution = solve(
        payload.roll_length,
        payload.kerf_width,
        segments_for_solve,
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
        for cut_pos, (sid, length, allowance, kit_id) in enumerate(
            zip(roll.segment_ids, roll.lengths, roll.allowances, roll.kit_ids),
            start=1,
        ):
            db_roll.cuts.append(
                Cut(
                    position=cut_pos,
                    segment_id=sid,
                    length=length,
                    allowance=allowance,
                    kit_id=kit_id,
                )
            )
        plan.rolls.append(db_roll)

    db.add(plan)
    db.commit()
    db.refresh(plan)
    return _plan_to_out(plan)


@app.get("/api/plans", response_model=list[PlanSummary])
def list_plans(db: Session = Depends(get_db)):
    return db.scalars(select(Plan).order_by(Plan.id.desc())).all()


def _get_plan_or_404(db: Session, plan_id: int) -> Plan:
    plan = db.get(Plan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="plan not found")
    return plan


@app.get("/api/plans/{plan_id}", response_model=PlanOut)
def get_plan(plan_id: int, db: Session = Depends(get_db)):
    return _plan_to_out(_get_plan_or_404(db, plan_id))


def _locked_roll_cuts(db: Session, plan_id: int, roll_position: int) -> list[Cut]:
    """Fetch a roll's cuts in canonical order, locking the rows for the
    duration of the transaction (PostgreSQL). 404 on unknown plan/roll."""
    _get_plan_or_404(db, plan_id)
    cuts = list(
        db.scalars(
            select(Cut)
            .join(Roll, Cut.roll_id == Roll.id)
            .where(Roll.plan_id == plan_id, Roll.position == roll_position)
            .order_by(Cut.position)
            .with_for_update()
        )
    )
    if not cuts:
        raise HTTPException(status_code=404, detail="roll not found")
    return cuts


def _completed_positions(cuts: list[Cut]) -> list[int]:
    return sorted(c.position for c in cuts if c.completed_at is not None)


@app.post("/api/plans/{plan_id}/rolls/{roll_position}/complete", response_model=PlanOut)
def complete_cut(
    plan_id: int,
    roll_position: int,
    action: CutAction,
    db: Session = Depends(get_db),
):
    """Record the next cut of one roll. Only the roll's first pending cut is
    accepted; stale/out-of-order requests conflict and change nothing."""
    try:
        cuts = _locked_roll_cuts(db, plan_id, roll_position)
        done = _completed_positions(cuts)
        next_position = len(done) + 1

        if next_position > len(cuts):
            raise HTTPException(
                status_code=409, detail="该卷所有段均已完成，请刷新后查看最新进度"
            )
        if action.position != next_position:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"只能按顺序完成第 {next_position} 段，页面可能已过期，请刷新"
                ),
            )

        target = cuts[next_position - 1]
        target.completed_at = datetime.now(timezone.utc)
        db.commit()
    except HTTPException:
        db.rollback()
        raise

    db.expire_all()
    return _plan_to_out(_get_plan_or_404(db, plan_id))


@app.post("/api/plans/{plan_id}/rolls/{roll_position}/undo", response_model=PlanOut)
def undo_cut(
    plan_id: int,
    roll_position: int,
    action: CutAction,
    db: Session = Depends(get_db),
):
    """Undo the last completed cut of one roll only."""
    try:
        cuts = _locked_roll_cuts(db, plan_id, roll_position)
        done = _completed_positions(cuts)

        if not done:
            raise HTTPException(
                status_code=409, detail="该卷还没有已完成的段，无可撤销内容"
            )
        last_position = done[-1]
        if action.position != last_position:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"只能撤销该卷最后完成的第 {last_position} 段，页面可能已过期，请刷新"
                ),
            )

        target = cuts[last_position - 1]
        target.completed_at = None
        db.commit()
    except HTTPException:
        db.rollback()
        raise

    db.expire_all()
    return _plan_to_out(_get_plan_or_404(db, plan_id))


# --- material review sheets (用料复核单) -------------------------------------

REVIEW_DUPLICATE_DETAIL = "该方案已建立用料复核单，不能重复建单"


def _sheet_to_out(sheet: ReviewSheet) -> ReviewSheetOut:
    return ReviewSheetOut(
        id=sheet.id,
        plan_id=sheet.plan_id,
        tolerance_mm=sheet.tolerance_mm,
        batch_ok=sheet.batch_ok,
        created_at=sheet.created_at,
        measurements=[
            ReviewMeasurementOut(
                roll_position=m.roll_position,
                theoretical_leftover=m.theoretical_leftover,
                measured_leftover=m.measured_leftover,
                deviation=m.deviation,
                ok=m.ok,
            )
            for m in sheet.measurements
        ],
    )


@app.post("/api/review-sheets", response_model=ReviewSheetOut, status_code=201)
def create_review_sheet(payload: ReviewSheetCreate, db: Session = Depends(get_db)):
    """Record one review sheet for a saved plan. The plan's stored leftovers
    are the baseline; every roll must be measured exactly once. The sheet,
    its per-roll deviations and both verdicts are persisted in a single
    transaction — the plan, its cuts and the cutting progress are never
    rewritten, and any validation error leaves no half-written sheet."""
    plan = db.get(Plan, payload.plan_id)
    if plan is None:
        raise HTTPException(
            status_code=422,
            detail=[_err(["plan_id"], f"plan {payload.plan_id} not found")],
        )

    # Canonical roll order -> theoretical leftover baseline.
    leftovers = {roll.position: roll.leftover for roll in plan.rolls}

    errors: list[dict] = []
    seen: set[int] = set()
    for i, m in enumerate(payload.measurements):
        position = m.roll_position
        if position in seen:
            errors.append(
                _err(
                    ["measurements", i, "roll_position"],
                    f"duplicate roll position {position}",
                )
            )
        elif position not in leftovers:
            errors.append(
                _err(
                    ["measurements", i, "roll_position"],
                    f"roll position {position} is not part of plan {plan.id}",
                )
            )
        else:
            seen.add(position)
    missing = [pos for pos in sorted(leftovers) if pos not in seen]
    if missing:
        errors.append(
            _err(
                ["measurements"],
                "missing measurements for roll position(s) "
                + ", ".join(str(pos) for pos in missing),
            )
        )
    if errors:
        raise HTTPException(status_code=422, detail=errors)

    # One sheet per plan; the unique constraint on plan_id is the backstop
    # for a race between two concurrent creations.
    existing = db.scalar(
        select(ReviewSheet.id).where(ReviewSheet.plan_id == plan.id)
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail=REVIEW_DUPLICATE_DETAIL)

    sheet = ReviewSheet(
        plan_id=plan.id,
        tolerance_mm=payload.tolerance_mm,
        batch_ok=True,
    )
    for m in payload.measurements:
        theoretical = leftovers[m.roll_position]
        deviation = abs(m.measured_leftover - theoretical)
        ok = deviation <= payload.tolerance_mm
        sheet.measurements.append(
            ReviewMeasurement(
                roll_position=m.roll_position,
                theoretical_leftover=theoretical,
                measured_leftover=m.measured_leftover,
                deviation=deviation,
                ok=ok,
            )
        )
        if not ok:
            sheet.batch_ok = False

    db.add(sheet)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=REVIEW_DUPLICATE_DETAIL)
    db.refresh(sheet)
    return _sheet_to_out(sheet)


@app.get("/api/review-sheets/{sheet_id}", response_model=ReviewSheetOut)
def get_review_sheet(sheet_id: int, db: Session = Depends(get_db)):
    sheet = db.get(ReviewSheet, sheet_id)
    if sheet is None:
        raise HTTPException(status_code=404, detail="review sheet not found")
    return _sheet_to_out(sheet)


@app.get("/api/plans/{plan_id}/review-sheet", response_model=ReviewSheetOut)
def get_plan_review_sheet(plan_id: int, db: Session = Depends(get_db)):
    _get_plan_or_404(db, plan_id)
    sheet = db.scalar(
        select(ReviewSheet).where(ReviewSheet.plan_id == plan_id)
    )
    if sheet is None:
        raise HTTPException(status_code=404, detail="review sheet not found")
    return _sheet_to_out(sheet)
