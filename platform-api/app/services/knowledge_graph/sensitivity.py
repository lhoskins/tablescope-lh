"""KG-08: shared sensitivity-label vocabulary and strictness ordering.

Today only two visibility values are ever written anywhere in the codebase
(``"shared_project"``, ``"private"`` -- on ``ProjectAsset``, ``ai_documents``,
and the otherwise-dead ``visibility`` column on ``AIProjectGraphNode``/
``AIProjectGraphEdge``). The review's fuller vocabulary (public-project,
project-restricted, shared-group, private, confidential, regulated) has no
storage or enforcement anywhere yet -- ``SavedQuery``, ``Dashboard``,
``DatabaseDataSource``, ``FileSourceMeta``, and ``ReferenceDocument`` carry
no visibility field at all, and there is no group-membership model behind
the already-present-but-always-null ``access_group_id`` columns. Adding all
of that is a materially larger, separate schema/UI effort, deliberately out
of scope here.

This module is the additive, non-schema-changing piece: a single ranked
vocabulary so any code that resolves or propagates a sensitivity label does
it consistently, rather than each call site inventing its own ordering.
"""

from __future__ import annotations

from collections.abc import Iterable

# Increasing strictness, left to right. An unrecognized/legacy value is
# treated as the current implicit default ("shared_project" -- every
# existing row that predates this vocabulary).
SENSITIVITY_LEVELS: tuple[str, ...] = (
    "public_project",
    "shared_project",
    "project_restricted",
    "shared_group",
    "private",
    "confidential",
    "regulated",
)

DEFAULT_SENSITIVITY = "shared_project"

_RANK_BY_LEVEL: dict[str, int] = {level: i for i, level in enumerate(SENSITIVITY_LEVELS)}


def sensitivity_rank(label: str | None) -> int:
    """Strictness rank of ``label`` -- higher means more restrictive.

    An unknown or missing label ranks the same as ``DEFAULT_SENSITIVITY``
    rather than raising, since most existing rows predate this vocabulary
    and legacy/unrecognized values must not be silently treated as either
    the least or the most restrictive by accident.
    """
    if label is None:
        return _RANK_BY_LEVEL[DEFAULT_SENSITIVITY]
    return _RANK_BY_LEVEL.get(label, _RANK_BY_LEVEL[DEFAULT_SENSITIVITY])


def strictest_sensitivity(labels: Iterable[str | None]) -> str:
    """The single most restrictive label among ``labels``.

    Evidence with no labels at all (an empty iterable) resolves to
    ``DEFAULT_SENSITIVITY`` -- derived content with no evidence to inherit
    a classification from is not, by that fact alone, more sensitive than
    the default.
    """
    labels = list(labels)
    if not labels:
        return DEFAULT_SENSITIVITY
    return max(labels, key=sensitivity_rank) or DEFAULT_SENSITIVITY
