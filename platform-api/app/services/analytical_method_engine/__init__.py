"""Analytical Method Engine.

Deterministic statistical-method selection and execution over a governed
catalog. The pipeline is: profile the data (Stage A), select a method from the
approved runtime registry (Stage B, never the LLM), execute it with assumption
gates (Stage C), and emit a structured, auditable result envelope (Stage D).

The LLM only ever *explains* the envelope — it never selects or invents results.
"""

from app.services.analytical_method_engine.config import EngineMode, get_engine_mode
from app.services.analytical_method_engine.engine import analyze

__all__ = ["analyze", "EngineMode", "get_engine_mode"]
