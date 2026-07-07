"""Unit tests for the cost-governance pure logic (no AWS calls)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from awscost import budgets, common, inventory, optimize, tagging  # noqa: E402


def _fake_inventory():
    return {
        "account": "988823366090",
        "generatedAt": "now",
        "regionsScanned": ["us-west-2"],
        "regions": {
            "us-west-2": {
                "ec2": [
                    {"InstanceId": "i-gpu", "Name": "tablescope-ai-server",
                     "Region": "us-west-2", "InstanceType": "g6.xlarge",
                     "State": "running", "IsGpu": True,
                     "MonthlyEstimateRunning": 587.50,
                     "Classification": "Production", "Tags": {}, "MissingTags": []},
                    {"InstanceId": "i-app", "Name": "tablescope",
                     "Region": "us-west-2", "InstanceType": "t3.large",
                     "State": "running", "IsGpu": False,
                     "MonthlyEstimateRunning": 60.74,
                     "Classification": "Production", "Tags": {}, "MissingTags": []},
                ],
                "ebs": [
                    {"VolumeId": "vol-free", "Region": "us-west-2", "SizeGiB": 100,
                     "VolumeType": "gp3", "State": "available", "AttachedTo": [],
                     "Unattached": True, "MonthlyEstimate": 8.0,
                     "Classification": "Unknown", "Tags": {}},
                ],
                "elasticIps": [
                    {"AllocationId": "eip-free", "PublicIp": "1.2.3.4",
                     "Region": "us-west-2", "AssociatedInstance": "",
                     "AssociatedEni": "", "Unattached": True,
                     "MonthlyEstimate": common.EIP_MONTH, "Tags": {}},
                ],
                "natGateways": [
                    {"NatGatewayId": "nat-1", "Region": "us-west-2", "Vpc": "vpc-1",
                     "Subnet": "sub-1", "State": "available",
                     "MonthlyEstimate": common.NAT_GATEWAY_MONTH, "Tags": {}},
                ],
                "other": {"Snapshots": [], "LoadBalancers": [], "VpcEndpoints": [],
                          "Amis": [], "CloudWatchLogGroups": [], "Lambda": [], "Rds": []},
            }
        },
        "global": {"Route53HostedZones": [], "S3Buckets": []},
    }


def test_classify_explicit_tag_authoritative():
    assert inventory.classify({"Environment": "Production"}, "whatever") == "Production"
    assert inventory.classify({"Environment": "Unknown"}, "tablescope") == "Unknown"
    assert inventory.classify({"Environment": "dev"}, "x") == "Development"


def test_classify_name_fallback():
    assert inventory.classify({}, "tablescope-ai-server") == "Production"
    assert inventory.classify({}, "random-scratch-box") == "Test"
    assert inventory.classify({}, "mystery") == "Unknown"


def test_gpu_detection_and_pricing():
    assert common.is_gpu_type("g6.xlarge")
    assert not common.is_gpu_type("t3.large")
    assert common.ec2_monthly("g6.xlarge") == round(0.8048 * 730, 2)
    assert common.ec2_monthly("nonexistent.type") is None


def test_ebs_pricing():
    assert common.ebs_monthly("gp3", 100) == 8.0
    assert common.ebs_monthly("gp2", 10) == 1.0


def test_budget_thresholds_are_percentages():
    notes = budgets._notifications()
    actual = [n for n in notes if n["Notification"]["NotificationType"] == "ACTUAL"]
    forecast = [n for n in notes if n["Notification"]["NotificationType"] == "FORECASTED"]
    assert len(actual) == len(budgets.ACTUAL_THRESHOLDS)
    assert len(forecast) == len(budgets.FORECAST_THRESHOLDS)
    # $50 of a $500 budget must map to 10%.
    assert actual[0]["Notification"]["Threshold"] == 10.0


def test_tagging_only_adds_missing():
    desired = tagging.desired_tags("tablescope-ai-server", True, "Production")
    assert desired["AutoStop"] == "True"
    assert desired["TablescopeRole"] == "AI-GPU"
    existing = {"Owner": "someone@else.com"}
    missing = tagging._missing(existing, desired)
    assert "Owner" not in missing  # never overwrite
    assert "AutoStop" in missing


def test_tagging_role_defaults():
    assert tagging._role_for("x", False, "Production") == ("Unclassified", "False")
    assert tagging._role_for("app-pritunl", False, "Production") == ("VPN", "False")
    assert tagging._role_for("", True, "Production") == ("AI-GPU", "True")


def test_recommendations_prioritise_gpu():
    recs = optimize.build_recommendations(_fake_inventory())
    assert recs[0]["resource"] == "i-gpu"
    # GPU scheduling saves ~61%.
    assert 350 < recs[0]["estMonthlySavings"] < 370
    kinds = {r["resource"] for r in recs}
    assert {"i-gpu", "vol-free", "eip-free", "nat-1", "i-app"} <= kinds


def test_scheduled_fraction():
    assert 0.38 < optimize.SCHEDULED_FRACTION < 0.39
