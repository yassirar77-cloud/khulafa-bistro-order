"""
Guard-rail tests for the Whisper vocabulary prompt.

Ensures get_whisper_prompt():
- returns a non-empty string
- stays under Whisper's 224-token ceiling
- keeps the top-3 sellers present
- keeps every PINNED_ITEMS entry present
- emits no duplicate items
- pins only items that actually exist in MENU

If a future edit drops a pinned item or pushes the prompt over budget,
these tests fail loudly.
"""
import pytest

from order_engine import MENU
from menu_validator import PINNED_ITEMS, get_whisper_prompt


def test_returns_string():
    prompt = get_whisper_prompt()
    assert isinstance(prompt, str)
    assert len(prompt) > 0


def test_under_token_budget():
    prompt = get_whisper_prompt()

    # Char-based sanity check — always runs, even without tiktoken.
    assert len(prompt) < 1000, f"prompt char length {len(prompt)} suspiciously large"

    # Strict token check using GPT-2 BPE (closest public proxy to Whisper's
    # multilingual tokenizer). Skip if tiktoken isn't installed — it's not
    # a runtime dependency, only a test-time check.
    tiktoken = pytest.importorskip("tiktoken")
    enc = tiktoken.get_encoding("gpt2")
    n_tokens = len(enc.encode(prompt))
    assert n_tokens < 224, f"prompt is {n_tokens} tokens, Whisper truncates at 224"


def test_contains_top_sellers():
    prompt = get_whisper_prompt().lower()
    for item in ("ais kosong", "roti canai", "nasi ayam"):
        assert item in prompt, f"top seller {item!r} missing from prompt"


def test_contains_pinned_anchors():
    prompt = get_whisper_prompt().lower()
    for item in PINNED_ITEMS:
        assert item in prompt, f"pinned anchor {item!r} missing from prompt"


def test_no_duplicate_items():
    prompt = get_whisper_prompt()
    # Strip the "Menu Khulafa Bistro Malaysia: " prefix and "Modifiers: ..." suffix
    # before splitting on commas so we compare item tokens only.
    _, _, after_prefix = prompt.partition(": ")
    items_section, _, _ = after_prefix.partition(". Modifiers:")
    items = [s.strip() for s in items_section.split(",") if s.strip()]
    assert len(items) == len(set(items)), f"duplicate items in prompt: {items}"


def test_all_pinned_items_exist_in_menu():
    for item in PINNED_ITEMS:
        assert item in MENU, f"pinned item {item!r} not in MENU — Whisper would hear a phantom"
