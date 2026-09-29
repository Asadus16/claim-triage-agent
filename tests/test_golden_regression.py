"""The regression gate: every golden case must produce its expected outcome.

This is the differentiator. It runs in CI on every prompt/rule change; if a
change silently alters a decision or a payout, the build fails here.
"""

import pytest

from app.golden import check_case, load_cases

CASES = load_cases()


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_golden_case(case):
    result = check_case(case)
    assert result.passed, "; ".join(result.failures)


def test_golden_set_is_substantial():
    # Guardrail against the set silently shrinking.
    assert len(CASES) >= 20
