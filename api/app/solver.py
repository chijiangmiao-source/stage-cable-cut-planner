"""Exact solver for the signal-wire roll cutting problem.

A roll holds a subset of segments. Each segment occupies its delivered
length plus its end-trim allowance (the actual cutting length) on the
roll. Adjacent segments inside a roll consume one kerf (saw cut) each;
the head and tail of a roll consume nothing. Segments are never split.

Segments may carry an optional kit id (套组编号): every segment sharing a
kit id is an indivisible set and must be delivered from a single roll
(the whole set can share that roll with other segments/kits). Segments
without a kit id keep packing independently, exactly as before. A kit
whose segments cannot fit one roll together (cut lengths plus the
internal kerfs between them) makes the whole request infeasible.

Objectives, applied in strict lexicographic order:

1. minimize the number of rolls used;
2. minimize total leftover material
   (note: total leftover == rolls * roll_length - sum(cut lengths)
    - kerf * (n - rolls), so once the roll count is fixed the total
    leftover is already determined);
3. tie-break for uniqueness: sort segment ids ascending inside each roll,
   sort the rolls lexicographically by their id sequences, then pick the
   overall lexicographically smallest plan.

With at most 12 segments an exact subset DP plus a greedy canonical
construction is both fast and deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Segment:
    sid: str
    length: int  # delivered length
    allowance: int = 0  # end-trim allowance
    kit_id: str | None = None  # optional indivisible kit (套组) marker

    @property
    def cut_length(self) -> int:
        """Actual length cut from the roll: delivered length + allowance."""
        return self.length + self.allowance


class KitPackingError(ValueError):
    """A kit's segments cannot be placed on a single roll together."""

    def __init__(self, kit_id: str, used_length: int, overflow_mm: int,
                 segment_ids: tuple[str, ...]) -> None:
        self.kit_id = kit_id
        self.used_length = used_length
        self.overflow_mm = overflow_mm
        self.segment_ids = segment_ids
        super().__init__(
            f"kit {kit_id!r} segments {list(segment_ids)} need {used_length} mm "
            f"including internal kerfs, overflowing a single roll by "
            f"{overflow_mm} mm"
        )


def find_kit_errors(
    roll_length: int, kerf_width: int, segments: list[Segment]
) -> list[KitPackingError]:
    """Return one error per kit whose members cannot share a roll.

    The required length counts every member's allowance and the kerfs
    *inside* the kit (m - 1 for m members); the head/tail of the eventual
    roll stay free, so adding other segments/kits can never make a failing
    kit fit. Independent segments (kit_id is None) are ignored.
    """
    totals: dict[str, int] = {}
    counts: dict[str, int] = {}
    members: dict[str, list[str]] = {}
    member_fits: dict[str, bool] = {}
    for seg in segments:
        if seg.kit_id is None:
            continue
        totals[seg.kit_id] = totals.get(seg.kit_id, 0) + seg.cut_length
        counts[seg.kit_id] = counts.get(seg.kit_id, 0) + 1
        members.setdefault(seg.kit_id, []).append(seg.sid)
        # A member that exceeds the roll on its own is already reported at the
        # length/allowance input; do not pile a kit error onto that kit until
        # the member fault is fixed.
        if seg.kit_id not in member_fits:
            member_fits[seg.kit_id] = True
        if seg.cut_length > roll_length:
            member_fits[seg.kit_id] = False

    errors: list[KitPackingError] = []
    for kit_id in sorted(totals):
        if not member_fits[kit_id]:
            continue
        cut_sum = totals[kit_id]
        m = counts[kit_id]
        used = cut_sum + kerf_width * (m - 1)
        if used > roll_length:
            errors.append(
                KitPackingError(
                    kit_id, used, used - roll_length, tuple(sorted(members[kit_id]))
                )
            )
    return errors


@dataclass(frozen=True)
class RollPlan:
    segment_ids: tuple[str, ...]  # cutting order: ids ascending
    lengths: tuple[int, ...]  # delivered lengths aligned with segment_ids
    allowances: tuple[int, ...]  # allowances aligned with segment_ids
    # Kit markers aligned with segment_ids; None for independent segments.
    kit_ids: tuple[str | None, ...]
    kerf_count: int  # len(segment_ids) - 1
    used_length: int  # sum(cut lengths) + kerf_width * kerf_count
    leftover: int  # roll_length - used_length


@dataclass(frozen=True)
class Solution:
    rolls: tuple[RollPlan, ...]  # already in canonical (sorted) order
    rolls_used: int
    total_kerf_count: int
    total_leftover: int


def solve(roll_length: int, kerf_width: int, segments: list[Segment]) -> Solution:
    if not segments:
        raise ValueError("at least one segment is required")
    for seg in segments:
        if seg.cut_length > roll_length:
            raise ValueError(
                f"segment {seg.sid!r} (cut length {seg.cut_length}) "
                f"exceeds roll length {roll_length}"
            )

    # Canonical index order: ids ascending.
    ordered = sorted(segments, key=lambda s: s.sid)
    ids = [s.sid for s in ordered]
    lens = [s.length for s in ordered]
    allows = [s.allowance for s in ordered]
    kits = [s.kit_id for s in ordered]
    cuts = [s.cut_length for s in ordered]
    n = len(ordered)
    full = (1 << n) - 1

    # Bit mask of each kit, in the first-appearance order of its marker.
    kit_masks: dict[str, int] = {}
    kit_order: list[str] = []
    for i, kit in enumerate(kits):
        if kit is None:
            continue
        if kit not in kit_masks:
            kit_masks[kit] = 0
            kit_order.append(kit)
        kit_masks[kit] |= 1 << i

    # fits[mask]: can the segments in `mask` share one roll?
    fits = [False] * (1 << n)
    fits[0] = True
    sum_len = [0] * (1 << n)
    count = [0] * (1 << n)
    for mask in range(1, 1 << n):
        lsb = mask & -mask
        i = lsb.bit_length() - 1
        prev = mask ^ lsb
        sum_len[mask] = sum_len[prev] + cuts[i]
        count[mask] = count[prev] + 1
        fits[mask] = sum_len[mask] + kerf_width * (count[mask] - 1) <= roll_length

    # A kit is indivisible: its members must land on one roll together,
    # accounting for every segment allowance and the kerfs between them.
    # A kit that does not fit a single roll at all can never be delivered.
    group_masks = [kit_masks[k] for k in kit_order]
    kit_errors = find_kit_errors(roll_length, kerf_width, ordered)
    if kit_errors:
        raise kit_errors[0]

    # allowed[mask]: `mask` may form one roll -- it fits and never splits a
    # kit (each kit is either wholly included or wholly absent). Singleton
    # masks of kit members are therefore forbidden; masks holding a whole
    # kit (possibly alongside other whole kits / independent segments) pass.
    allowed = [False] * (1 << n)
    allowed[0] = True
    for mask in range(1, 1 << n):
        if not fits[mask]:
            continue
        ok = True
        for gm in group_masks:
            inter = mask & gm
            if inter != 0 and inter != gm:
                ok = False
                break
        allowed[mask] = ok

    # can[mask]: minimum number of rolls needed for the segments in `mask`.
    INF = n + 1
    can = [INF] * (1 << n)
    can[0] = 0
    for mask in range(1, 1 << n):
        best = INF
        sub = mask
        while sub:
            if allowed[sub] and can[mask ^ sub] + 1 < best:
                best = can[mask ^ sub] + 1
            sub = (sub - 1) & mask
        can[mask] = best

    rolls_used = can[full]

    # Greedy canonical construction: the roll holding the smallest remaining
    # id always sorts first, so pick the lexicographically smallest feasible
    # id tuple for it such that the remainder still packs into left - 1 rolls.
    rolls: list[RollPlan] = []
    remaining = full
    left = rolls_used
    while remaining:
        lo = (remaining & -remaining).bit_length() - 1
        chosen = None
        for cand in _enum_candidates(remaining, lo):
            if allowed[cand] and can[remaining ^ cand] <= left - 1:
                chosen = cand
                break
        if chosen is None:  # pragma: no cover - unreachable given the DP above
            raise RuntimeError("no feasible roll found during canonical construction")

        rids: list[str] = []
        rlens: list[int] = []
        rallows: list[int] = []
        rkits: list[str | None] = []
        bits = chosen
        while bits:
            lsb = bits & -bits
            i = lsb.bit_length() - 1
            rids.append(ids[i])
            rlens.append(lens[i])
            rallows.append(allows[i])
            rkits.append(kits[i])
            bits ^= lsb

        kerf_count = len(rids) - 1
        used = (
            sum(length + allowance for length, allowance in zip(rlens, rallows))
            + kerf_width * kerf_count
        )
        rolls.append(
            RollPlan(
                segment_ids=tuple(rids),
                lengths=tuple(rlens),
                allowances=tuple(rallows),
                kit_ids=tuple(rkits),
                kerf_count=kerf_count,
                used_length=used,
                leftover=roll_length - used,
            )
        )
        remaining ^= chosen
        left -= 1

    return Solution(
        rolls=tuple(rolls),
        rolls_used=rolls_used,
        total_kerf_count=sum(r.kerf_count for r in rolls),
        total_leftover=sum(r.leftover for r in rolls),
    )


def _enum_candidates(mask: int, lo: int):
    """Yield subsets of `mask` containing bit `lo`, ordered by the
    lexicographic order of their ascending-id tuples."""
    base = 1 << lo
    yield base
    higher = mask & ~((1 << (lo + 1)) - 1)
    yield from _extend(base, higher)


def _extend(prefix: int, higher: int):
    bits = higher
    while bits:
        lsb = bits & -bits
        j = lsb.bit_length() - 1
        new_prefix = prefix | lsb
        yield new_prefix
        yield from _extend(new_prefix, higher & ~((1 << (j + 1)) - 1))
        bits ^= lsb
