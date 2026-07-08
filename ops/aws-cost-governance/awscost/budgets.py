"""Phase 8 - AWS Budgets (actual + forecast alerts).

Creates a single monthly cost budget carrying all required notification
thresholds (keeps the per-budget charge to a minimum) plus optional SNS
fan-out. Idempotent: re-running updates the budget in place.
"""
from __future__ import annotations

import os
from typing import Any

from botocore.exceptions import ClientError

from . import common as C

BUDGET_NAME = "tablescope-monthly-cost-governance"
BUDGET_LIMIT = 500.0

# (threshold_usd, notification_type)
ACTUAL_THRESHOLDS = [50, 100, 200, 300, 500]
FORECAST_THRESHOLDS = [200, 300, 500]


def _subscribers() -> list[dict[str, str]]:
    subs = [{"SubscriptionType": "EMAIL", "Address": C.NOTIFY_EMAIL}]
    topic = os.environ.get(C.SNS_TOPIC_ENV)
    if topic:
        subs.append({"SubscriptionType": "SNS", "Address": topic})
    return subs


def _notifications() -> list[dict[str, Any]]:
    subs = _subscribers()
    out: list[dict[str, Any]] = []
    for usd in ACTUAL_THRESHOLDS:
        out.append({
            "Notification": {
                "NotificationType": "ACTUAL",
                "ComparisonOperator": "GREATER_THAN",
                "Threshold": round(usd / BUDGET_LIMIT * 100, 2),
                "ThresholdType": "PERCENTAGE",
            },
            "Subscribers": subs,
        })
    for usd in FORECAST_THRESHOLDS:
        out.append({
            "Notification": {
                "NotificationType": "FORECASTED",
                "ComparisonOperator": "GREATER_THAN",
                "Threshold": round(usd / BUDGET_LIMIT * 100, 2),
                "ThresholdType": "PERCENTAGE",
            },
            "Subscribers": subs,
        })
    return out


def apply(dry_run: bool = True) -> dict[str, Any]:
    account = C.client("sts").get_caller_identity()["Account"]
    budgets = C.client("budgets", "us-east-1")
    budget = {
        "BudgetName": BUDGET_NAME,
        "BudgetLimit": {"Amount": str(BUDGET_LIMIT), "Unit": "USD"},
        "TimeUnit": "MONTHLY",
        "BudgetType": "COST",
    }
    plan = {
        "budget": BUDGET_NAME,
        "limit": BUDGET_LIMIT,
        "actualThresholds": ACTUAL_THRESHOLDS,
        "forecastThresholds": FORECAST_THRESHOLDS,
        "notify": [s["Address"] for s in _subscribers()],
        "action": "dry-run",
    }
    if dry_run:
        return plan

    try:
        budgets.create_budget(
            AccountId=account, Budget=budget,
            NotificationsWithSubscribers=_notifications())
        plan["action"] = "created"
    except ClientError as e:
        if e.response["Error"]["Code"] != "DuplicateRecordException":
            raise
        # Update limit, then reconcile notifications.
        budgets.update_budget(AccountId=account, NewBudget=budget)
        existing = budgets.describe_notifications_for_budget(
            AccountId=account, BudgetName=BUDGET_NAME).get("Notifications", [])
        for n in existing:
            try:
                budgets.delete_notification(
                    AccountId=account, BudgetName=BUDGET_NAME, Notification=n)
            except ClientError:
                pass
        for nws in _notifications():
            budgets.create_notification(
                AccountId=account, BudgetName=BUDGET_NAME,
                Notification=nws["Notification"], Subscribers=nws["Subscribers"])
        plan["action"] = "updated"
    return plan
