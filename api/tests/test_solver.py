"""Solver tests, including differential testing against a brute-force
enumeration of all set partitions."""

import random

import pytest

from app.solver import KitPackingError, Segment, solve


def ids_rolls(solution):
    return tuple(roll.segment_ids for roll in solution.rolls)


def test_single_segment_no_kerf():
    sol = solve(1000, 10, [Segment("A", 400)])
    assert sol.rolls_used == 1
    assert sol.rolls[0].kerf_count == 0
    assert sol.rolls[0].leftover == 600
    assert sol.total_leftover == 600
    assert sol.total_kerf_count == 0


def test_kerf_forces_extra_roll():
    # 50 + 50 + kerf 30 = 130 > 100, so two rolls are needed even though
    # the raw lengths alone would fit in one roll.
    sol = solve(100, 30, [Segment("A", 50), Segment("B", 50)])
    assert sol.rolls_used == 2
    assert ids_rolls(sol) == (("A",), ("B",))
    assert sol.total_kerf_count == 0
    assert sol.total_leftover == 200 - 100  # 2 * 100 - 100


def test_exact_fit_with_kerf():
    # 600 + 390 + 1 kerf of 10 = 1000 exactly.
    sol = solve(1000, 10, [Segment("A", 600), Segment("B", 390)])
    assert sol.rolls_used == 1
    assert sol.rolls[0].kerf_count == 1
    assert sol.rolls[0].leftover == 0


def test_tie_break_picks_lexicographically_smallest():
    # Four equal wires, two per roll: {AB,CD} < {AC,BD} < {AD,BC}.
    sol = solve(
        100,
        5,
        [Segment("C", 40), Segment("A", 40), Segment("D", 40), Segment("B", 40)],
    )
    assert sol.rolls_used == 2
    assert ids_rolls(sol) == (("A", "B"), ("C", "D"))
    assert all(r.kerf_count == 1 for r in sol.rolls)
    assert all(r.leftover == 100 - 40 - 40 - 5 for r in sol.rolls)


def test_greedy_must_skip_singleton_when_remainder_infeasible():
    # (A,) is lexicographically smallest but leaves {B,C} unpackable in one
    # roll, so the first roll must grow.
    sol = solve(
        100,
        5,
        [Segment("A", 60), Segment("B", 90), Segment("C", 30)],
    )
    # A+B: 60+90+5 > 100; A+C: 60+30+5 <= 100; B+C: 90+30+5 > 100
    assert sol.rolls_used == 2
    assert ids_rolls(sol) == (("A", "C"), ("B",))


def test_roll_ids_sorted_and_rolls_sorted():
    sol = solve(
        1000,
        10,
        [Segment("W3", 300), Segment("W1", 100), Segment("W2", 200)],
    )
    assert ids_rolls(sol) == (("W1", "W2", "W3"),)


def test_total_leftover_identity():
    segs = [Segment(chr(ord("A") + i), 10 * (i + 1)) for i in range(6)]
    roll_length, kerf = 200, 7
    sol = solve(roll_length, kerf, segs)
    total = sum(s.length for s in segs)
    expected = sol.rolls_used * roll_length - total - kerf * (len(segs) - sol.rolls_used)
    assert sol.total_leftover == expected
    assert sol.total_leftover == sum(r.leftover for r in sol.rolls)
    assert sol.total_kerf_count == len(segs) - sol.rolls_used


def test_segment_equal_to_roll_length_fits_alone():
    sol = solve(500, 10, [Segment("A", 500), Segment("B", 1)])
    assert sol.rolls_used == 2
    assert ids_rolls(sol) == (("A",), ("B",))


def test_oversized_segment_rejected():
    with pytest.raises(ValueError):
        solve(100, 5, [Segment("A", 101)])


# ---------------------------------------------------------------------------
# End-trim allowance: the cut length (length + allowance) occupies the roll.
# ---------------------------------------------------------------------------


def test_allowance_counts_toward_capacity():
    # Cut lengths 60 and 50: 60 + 50 + 5 kerf = 115 > 110, so two rolls.
    # Without the allowance the same segments would share one roll (105 <= 110).
    segs = [Segment("A", 50, 10), Segment("B", 50)]
    assert solve(110, 5, segs).rolls_used == 2
    assert solve(110, 5, [Segment("A", 50), Segment("B", 50)]).rolls_used == 1


def test_allowance_exact_fit_with_kerf():
    # Cut lengths 500 + 490 plus one kerf of 10 fill the roll exactly.
    sol = solve(1000, 10, [Segment("A", 400, 100), Segment("B", 490)])
    assert sol.rolls_used == 1
    assert sol.rolls[0].kerf_count == 1
    assert sol.rolls[0].used_length == 1000
    assert sol.rolls[0].leftover == 0


def test_roll_plan_carries_delivered_lengths_and_allowances():
    sol = solve(1000, 10, [Segment("B", 300), Segment("A", 400, 50)])
    roll = sol.rolls[0]
    assert roll.segment_ids == ("A", "B")
    assert roll.lengths == (400, 300)  # delivered lengths, not cut lengths
    assert roll.allowances == (50, 0)
    assert roll.used_length == 400 + 50 + 300 + 10
    # Totals still close: leftover = rolls * roll_length - cuts - kerfs.
    assert sol.total_leftover == 1000 - 750 - 10


def test_oversized_cut_length_rejected():
    with pytest.raises(ValueError):
        solve(100, 5, [Segment("A", 100, 1)])


def test_twelve_segments_run_quickly():
    segs = [Segment(f"S{i:02d}", 97 + 3 * i) for i in range(12)]
    sol = solve(400, 11, segs)
    assert sol.rolls_used >= 3
    # every roll feasible and every segment delivered exactly once
    delivered = sorted(sid for r in sol.rolls for sid in r.segment_ids)
    assert delivered == sorted(s.sid for s in segs)
    for roll in sol.rolls:
        assert roll.used_length <= 400


# ---------------------------------------------------------------------------
# Kits (套组): segments sharing a kit id are indivisible across rolls.
# ---------------------------------------------------------------------------


def test_kit_keeps_members_on_one_roll_when_packing_would_split_them():
    # Independent optimum is [A], [B,C] (A=400, B=400, C=300, roll 1000).
    # Marking A and B as one kit forbids splitting them: [A,B]=810, C alone.
    segs = [Segment("A", 400, kit_id="K1"), Segment("B", 400, kit_id="K1"),
            Segment("C", 300)]
    sol = solve(1000, 10, segs)
    assert sol.rolls_used == 2
    assert ids_rolls(sol) == (("A", "B"), ("C",))
    first = sol.rolls[0]
    assert first.kit_ids == ("K1", "K1")
    assert sol.rolls[1].kit_ids == (None,)
    assert first.used_length == 400 + 400 + 10
    assert first.leftover == 190


def test_kit_roll_may_share_with_other_segments_and_rolls_close():
    # Kit {A,C}; the lexicographically smallest feasible first roll that
    # leaves a feasible remainder is {A,B,C} (920 <= 1000), then {D}.
    segs = [
        Segment("A", 300, kit_id="K1"),
        Segment("B", 300),
        Segment("C", 300, kit_id="K1"),
        Segment("D", 300),
    ]
    sol = solve(1000, 10, segs)
    assert sol.rolls_used == 2
    assert ids_rolls(sol) == (("A", "B", "C"), ("D",))
    for roll in sol.rolls:
        cut_sum = sum(
            length + allowance
            for length, allowance in zip(roll.lengths, roll.allowances)
        )
        assert roll.used_length == cut_sum + 10 * roll.kerf_count
        assert roll.used_length + roll.leftover == 1000


def test_kit_marks_every_cut_aligned_with_its_order():
    segs = [
        Segment("C", 100, kit_id="G2"),
        Segment("A", 100, kit_id="G1"),
        Segment("B", 100, kit_id="G1"),
    ]
    sol = solve(1000, 10, segs)
    (roll,) = sol.rolls
    assert roll.segment_ids == ("A", "B", "C")
    assert roll.kit_ids == ("G1", "G1", "G2")


def test_distinct_kits_and_independent_segments_coexist():
    segs = [
        Segment("A", 200, kit_id="K1"),
        Segment("B", 200, kit_id="K2"),
        Segment("C", 200, kit_id="K1"),
        Segment("D", 200, kit_id="K2"),
        Segment("E", 200),
    ]
    sol = solve(1000, 10, segs)
    # one roll: 5*200 + 4*10 = 1040 > 1000, so two rolls; each kit intact
    assert sol.rolls_used == 2
    roll_of = {
        sid: pos
        for pos, r in enumerate(sol.rolls, start=1)
        for sid in r.segment_ids
    }
    assert roll_of["A"] == roll_of["C"]
    assert roll_of["B"] == roll_of["D"]


def test_single_member_kit_behaves_like_independent_segment():
    with_kit = solve(1000, 10, [
        Segment("A", 600, kit_id="SOLO"),
        Segment("B", 590),
        Segment("C", 400),
    ])
    without = solve(1000, 10, [
        Segment("A", 600), Segment("B", 590), Segment("C", 400),
    ])
    assert ids_rolls(with_kit) == ids_rolls(without) == (("A",), ("B", "C"))
    assert with_kit.rolls[0].kit_ids == ("SOLO",)


def test_kit_allowance_and_internal_kerfs_count_toward_capacity():
    # Cut lengths 300 and 200 plus one internal kerf of 10 = 510 > 500:
    # the kit cannot share one roll even though each segment alone fits.
    segs = [Segment("A", 300, allowance=0, kit_id="K1"),
            Segment("B", 150, allowance=50, kit_id="K1")]
    with pytest.raises(KitPackingError) as exc:
        solve(500, 10, segs)
    assert exc.value.kit_id == "K1"
    assert exc.value.overflow_mm == 10
    assert exc.value.used_length == 510
    assert exc.value.segment_ids == ("A", "B")


def test_kit_members_sorted_in_error():
    segs = [Segment("B", 400, kit_id="K1"), Segment("A", 400, kit_id="K1")]
    with pytest.raises(KitPackingError) as exc:
        solve(700, 10, segs)  # 400+400+10 = 810 > 700
    assert exc.value.segment_ids == ("A", "B")
    assert exc.value.overflow_mm == 110


def test_kit_overflow_is_reported_even_if_other_segments_could_join():
    # The kit by itself already exceeds the roll; extra segments are moot.
    segs = [Segment("A", 600, kit_id="K1"), Segment("B", 600, kit_id="K1"),
            Segment("C", 10)]
    with pytest.raises(KitPackingError):
        solve(1000, 10, segs)


# ---------------------------------------------------------------------------
# Differential testing against brute force.
# ---------------------------------------------------------------------------

def _partitions(n):
    """Yield every set partition of range(n) as a list of frozensets."""
    if n == 0:
        yield []
        return
    for rest in _partitions(n - 1):
        yield rest + [frozenset({n - 1})]
        for i in range(len(rest)):
            yield rest[:i] + [rest[i] | {n - 1}] + rest[i + 1 :]


def _brute_force(roll_length, kerf, segments, kit_labels=None):
    n = len(segments)
    ids = [s.sid for s in segments]
    cuts = [s.cut_length for s in segments]
    kit_labels = kit_labels or [None] * n
    kit_members: dict = {}
    for i, label in enumerate(kit_labels):
        if label is not None:
            kit_members.setdefault(label, set()).add(i)

    def fits(block):
        return sum(cuts[i] for i in block) + kerf * (len(block) - 1) <= roll_length

    def kits_intact(part):
        block_of = {}
        for bi, block in enumerate(part):
            for i in block:
                block_of[i] = bi
        return all(
            len({block_of[i] for i in members}) == 1
            for members in kit_members.values()
        )

    best_key = None
    best_canonical = None
    for part in _partitions(n):
        if not all(fits(b) for b in part):
            continue
        if not kits_intact(part):
            continue
        canonical = tuple(sorted(tuple(sorted(ids[i] for i in b)) for b in part))
        key = (len(part), canonical)
        if best_key is None or key < best_key:
            best_key = key
            best_canonical = canonical
    return best_canonical


def _random_kit_labels(rng, n):
    """Group a random subset of segments into kits of size >= 2."""
    labels = [None] * n
    next_label = 0
    for i in range(n):
        if labels[i] is not None:
            continue
        if n >= 2 and rng.random() < 0.4:
            j = rng.randrange(n - 1)
            if j >= i:
                j += 1
            label = labels[j]
            if label is None:
                label = next_label
                next_label += 1
                labels[j] = label
            labels[i] = label
    return labels


@pytest.mark.parametrize("seed", range(60))
def test_matches_brute_force(seed):
    rng = random.Random(seed)
    n = rng.randint(1, 8)
    roll_length = rng.randint(30, 120)
    kerf = rng.randint(1, 20)
    segments = []
    for i in range(n):
        length = rng.randint(1, roll_length)
        # Random allowance, always keeping the segment deliverable.
        allowance = rng.randint(0, roll_length - length)
        segments.append(Segment(f"S{i}", length, allowance))
    sol = solve(roll_length, kerf, segments)
    expected = _brute_force(roll_length, kerf, segments)
    assert ids_rolls(sol) == expected
    assert sol.rolls_used == len(expected)


@pytest.mark.parametrize("seed", range(120))
def test_matches_brute_force_with_kits(seed):
    rng = random.Random(1000 + seed)
    n = rng.randint(2, 8)
    roll_length = rng.randint(30, 120)
    kerf = rng.randint(1, 20)
    labels = _random_kit_labels(rng, n)
    segments = []
    for i in range(n):
        length = rng.randint(1, roll_length)
        allowance = rng.randint(0, roll_length - length)
        kit = f"K{labels[i]}" if labels[i] is not None else None
        segments.append(Segment(f"S{i}", length, allowance, kit))

    expected = _brute_force(roll_length, kerf, segments, labels)
    if expected is None:
        # Some kit cannot fit one roll: the solver must refuse rather than
        # silently split it.
        with pytest.raises(KitPackingError):
            solve(roll_length, kerf, segments)
        return

    sol = solve(roll_length, kerf, segments)
    assert ids_rolls(sol) == expected
    assert sol.rolls_used == len(expected)
    # No kit spans two rolls.
    roll_of = {
        sid: pos
        for pos, r in enumerate(sol.rolls, start=1)
        for sid in r.segment_ids
    }
    for seg, label in zip(segments, labels):
        if label is None:
            continue
        mates = [s.sid for s, l in zip(segments, labels) if l == label]
        assert len({roll_of[m] for m in mates}) == 1
        assert sol.rolls[roll_of[seg.sid] - 1].used_length <= roll_length
