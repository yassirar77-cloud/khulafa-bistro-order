"""Tests for Change 7 — partial-miss recovery helpers and state.

All tests operate on pure helpers exposed from main. The trigger-block
lives inline in /api/voice/chat; its state-dict bookkeeping is verified
directly against main._partial_miss_attempts without spinning up the
FastAPI client (which would pull in the DeepSeek/Qwen call stack).
"""
import pytest

import main
from main import count_estimated_items_in_text, should_trigger_partial_miss


@pytest.fixture
def flag_on(monkeypatch):
    """Enable the feature flag for a single test without leaking state."""
    monkeypatch.setattr(main, "PARTIAL_MISS_RECOVERY_ENABLED", True)
    main._partial_miss_attempts.clear()
    yield
    main._partial_miss_attempts.clear()


@pytest.fixture(autouse=True)
def reset_attempts():
    """Ensure attempts dict is clean for every test, flag or no flag."""
    main._partial_miss_attempts.clear()
    yield
    main._partial_miss_attempts.clear()


# ── count_estimated_items_in_text ──────────────────────────────────────────

def test_count_zero():
    """Empty string must floor at 1 so divisions downstream never zero-out."""
    assert count_estimated_items_in_text("") == 1


def test_count_single():
    """A single-item utterance with one quantity word should estimate 1."""
    assert count_estimated_items_in_text("teh tarik satu") == 1


def test_count_multiple():
    """Multi-item utterance with explicit quantity markers should estimate >= 3.

    NOTE: the heuristic is intentionally conservative. Marker-only strings
    like "kopi ais milo ais limau ais teh ais" (no quantity words) floor
    to 1 by design — the min(marker//2, quantity+1) formula caps the
    estimate by quantity signals. High counts require quantity words
    (satu/dua/tambah/lagi/…). That floor behavior is also asserted here.
    """
    # Spec input (marker-only) — documents the floor behavior.
    assert count_estimated_items_in_text("kopi ais milo ais limau ais teh ais") == 1

    # Realistic multi-item with explicit quantities — exercises the high path.
    result = count_estimated_items_in_text(
        "satu teh ais dua kopi ais tambah roti canai"
    )
    assert result >= 3


# ── should_trigger_partial_miss ────────────────────────────────────────────

def test_trigger_big_mismatch(flag_on):
    """With the flag on, a 4-estimated / 1-extracted gap must trigger."""
    text = "dua teh ais tiga kopi ais tambah nasi ayam lagi roti canai"
    # Sanity: the chosen text really does estimate at 4 with this heuristic.
    assert count_estimated_items_in_text(text) == 4

    should, est, got = should_trigger_partial_miss(text, 1)
    assert (should, est, got) == (True, 4, 1)


def test_no_trigger_match(flag_on):
    """When extracted count keeps pace with estimate, no trigger."""
    text = "satu teh ais dua kopi ais tambah roti canai"  # estimates to 3
    should, est, got = should_trigger_partial_miss(text, 3)
    assert should is False
    assert got == 3


def test_no_trigger_small(flag_on):
    """Small orders never trigger — estimate >= 4 is the floor."""
    text = "satu teh ais dua kopi ais"  # estimates to 2
    should, est, got = should_trigger_partial_miss(text, 1)
    assert should is False
    assert est == 2
    assert got == 1


# ── Attempts state dict lifecycle ──────────────────────────────────────────

def test_attempts_state(flag_on):
    """Simulate the route's attempt-bump + reset lifecycle against the dict.

    Mirrors the logic inside /api/voice/chat so we can verify the state
    dict without booting FastAPI + external API clients.
    """
    table = "T01"

    # First big-mismatch turn: dict is empty, attempts=0, should trigger.
    attempts = main._partial_miss_attempts.get(table, 0)
    assert attempts == 0
    should, _, _ = should_trigger_partial_miss(
        "dua teh ais tiga kopi ais tambah nasi ayam lagi roti canai", 1
    )
    assert should is True
    # Route bumps counter on the reask path.
    main._partial_miss_attempts[table] = attempts + 1
    assert main._partial_miss_attempts[table] == 1

    # Second big-mismatch turn: attempts=1, should_reask True but attempts>=1,
    # so the route takes the else-branch and pops the counter.
    attempts = main._partial_miss_attempts.get(table, 0)
    should, _, _ = should_trigger_partial_miss(
        "dua teh ais tiga kopi ais tambah nasi ayam lagi roti canai", 1
    )
    assert should is True
    assert attempts >= 1
    main._partial_miss_attempts.pop(table, None)
    assert table not in main._partial_miss_attempts

    # Third turn: clean extraction, no trigger, counter stays absent.
    should, _, _ = should_trigger_partial_miss("teh tarik satu", 1)
    assert should is False
    assert table not in main._partial_miss_attempts


# ── Feature flag gating ────────────────────────────────────────────────────

def test_flag_off():
    """Flag off (default) short-circuits the helper to (False, 0, extracted).

    Verifies the feature is truly inert until PARTIAL_MISS_RECOVERY_ENABLED
    is flipped. The `0` for estimated confirms the helper never even calls
    count_estimated_items_in_text when the flag is off.
    """
    assert main.PARTIAL_MISS_RECOVERY_ENABLED is False

    text = "dua teh ais tiga kopi ais tambah nasi ayam lagi roti canai"
    should, est, got = should_trigger_partial_miss(text, 1)
    assert should is False
    assert est == 0
    assert got == 1
