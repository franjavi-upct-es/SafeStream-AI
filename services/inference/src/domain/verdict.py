# services/inference/src/domain/verdict.py
"""Map raw model scores to a categorical verdict.

The downstream auditing UI only cares about three buckets:

  * ``safe``    - max(scores) < threshold_review    (auto-pass)
  * ``review``  - threshold_review <= max(scores) < threshold_block
  * ``block``   - max(scores) >= threshold_block    (auto-block)

Keeping this in a tiny module means the worker and the REST handlers share
the exact same rule.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from config import settings

Verdict = Literal["safe", "review", "block"]


def derive_verdict(
    scores: Mapping[str, float],
    *,
    threshold_review: float | None = None,
    threshold_block: float | None = None,
) -> Verdict:
    """Reduce a dict of label→probability to a verdict.

    Empty ``scores`` map to ``safe`` so a model that abstains never blocks.
    """

    review = (
        settings.threshold_review
        if threshold_review is None
        else threshold_review
    )
    block = (
        settings.threshold_block if threshold_block is None else threshold_block
    )

    if not scores:
        return "safe"

    top = max(scores.values())
    if top >= block:
        return "block"
    if top >= review:
        return "review"
    return "safe"
