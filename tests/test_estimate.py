from __future__ import annotations

from costanza.constants import skeleton
from costanza.estimate import budget_state, file_tokens


def test_tiny_and_near_token_counts(tiny_text: str, near_text: str) -> None:
    assert file_tokens(tiny_text) == 238
    assert file_tokens(near_text) == 1666


def test_skeleton_shopbot_tokens() -> None:
    assert file_tokens(skeleton("shopbot")) == 94


def test_budget_states() -> None:
    assert budget_state(1619, 1800, 0.90) == "ok"
    assert budget_state(1620, 1800, 0.90) == "warn"
    assert budget_state(1800, 1800, 0.90) == "warn"
    assert budget_state(1801, 1800, 0.90) == "over"
