"""Tests for the "why" investigation trigger in conversational_analytics.

A pure keyword/pattern check, not an LLM call -- these confirm it fires for
genuine root-cause questions and stays quiet for plain factual ones, since
the whole point is to keep the common case (most questions) on the existing
single-query path with zero extra cost.
"""

from __future__ import annotations

import pytest

from app.services.conversational_analytics.intent_classification import (
    _is_investigative_question,
)


@pytest.mark.parametrize(
    "question",
    [
        "Why is the defect rate rising?",
        "why did shipments slow down last quarter",
        "What's driving the increase in backup job failures?",
        "What is driving customer churn?",
        "What is causing the delay in order fulfillment?",
        "What's the root cause of the CAPA backlog?",
        "What explains the spike in support tickets?",
        "What is the reason for the drop in revenue?",
        "What's the reason behind the outage?",
        "What are the driving factors behind late deliveries?",
        "What are the contributing factors to low inventory?",
    ],
)
def test_detects_investigative_questions(question: str) -> None:
    assert _is_investigative_question(question) is True


@pytest.mark.parametrize(
    "question",
    [
        "What is the total revenue this quarter?",
        "Show me backup job failure rate",
        "List the top 5 suppliers by defect count",
        "How many open tickets are there?",
        "Change the chart to a line chart",
        "Group sales by region",
    ],
)
def test_leaves_plain_factual_questions_alone(question: str) -> None:
    assert _is_investigative_question(question) is False
