"""Structured CSV dataset generators for the demo company.

Every table is derived from the shared :class:`Dimensions` so ids line up
across departments (referential integrity by construction).  Financial facts
are built from the same revenue / labor / material / scrap series that feed the
GL, so budget-vs-actual, forecast variance and the planted AI stories are
internally consistent rather than independent random noise.

All dates are rolled forward to the issue's window: monthly tables through
2026-07-01, weekly tables through 2026-07-06.
"""

from __future__ import annotations

import random

from . import config as C
from .dimensions import Dimensions
from .ehs import _ehs
from .engineering import _engineering
from .executive import _executive
from .finance import _finance
from .hr import _hr
from .io_utils import Registry
from .it import _it
from .legal import _legal
from .manufacturing import _manufacturing
from .procurement import _procurement
from .quality import _quality
from .sales import _sales


def generate_datasets(reg: Registry, dims: Dimensions) -> None:
    rng = random.Random(dims.spec.seed ^ 0x5F3759DF)
    months = C.month_starts(C.MONTHLY_START, C.MONTHLY_THROUGH)
    weeks = C.week_mondays(C.WEEKLY_START, C.WEEKLY_THROUGH)

    revenue = _sales(reg, dims, rng, months)
    material = _manufacturing(reg, dims, rng, months, weeks)
    labor = _engineering(reg, dims, rng, months)
    _finance(reg, dims, rng, months, revenue, material, labor)
    _hr(reg, dims, rng, months)
    _quality(reg, dims, rng, months, weeks)
    _procurement(reg, dims, rng, months)
    _it(reg, dims, rng, months)
    _ehs(reg, dims, rng, months)
    _legal(reg, dims, rng)
    _executive(reg, dims, rng, months, revenue)
