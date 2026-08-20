from app.models.dashboard_template import DashboardGroup
from app.services.operational_insight_dashboards import operational_insight_config


def test_operational_config_stamps_full_framework_and_preserves_wiring():
    group = DashboardGroup(
        id=7,
        tenant_id=33,
        project_id=44,
        name="Custom dashboards",
        slug="custom-dashboards",
        icon="activity",
        position=0,
        collapsed_default=True,
    )
    config = operational_insight_config(
        {
            "widgets": [
                {
                    "id": "risk",
                    "dataSource": {"kind": "query", "queryId": 99},
                    "visualizationOptions": {"showLegend": False},
                }
            ]
        },
        group=group,
        dashboard_name="High-Risk IT Changes",
    )

    assert config["presentation"] == "operational_insight"
    assert config["layout"] == "operational_grid"
    assert config["dashboardGroupId"] == 7
    assert config["dashboardTemplate"]["groupId"] == "group:7"
    assert config["widgets"][0]["dataSource"]["queryId"] == 99
    assert config["widgets"][0]["visualizationOptions"] == {
        "showLegend": False,
        "colorScheme": "operational_insight",
    }
