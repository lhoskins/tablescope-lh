"""Unstructured document generators (Markdown) for the demo company."""

from __future__ import annotations

import random

from .business_ops import _business_ops
from .dimensions import Dimensions
from .executive_reviews import _executive_reviews
from .io_utils import Registry
from .policies import _policies
from .procedures import _procedures


def generate_documents(reg: Registry, dims: Dimensions) -> None:
    rng = random.Random(dims.spec.seed ^ 0x1234ABCD)
    _policies(reg, dims)
    _procedures(reg, dims)
    _executive_reviews(reg, dims, rng)
    _business_ops(reg, dims, rng)
