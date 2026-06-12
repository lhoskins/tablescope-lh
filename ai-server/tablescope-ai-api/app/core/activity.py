"""Track last activity for idle auto-stop."""

import json
import os
from datetime import datetime, timezone

from app.core.config import settings

ACTIVITY_FILE = os.path.join(settings.data_mount, "runtime", "last_activity.json")
# Fallback when the data mount doesn't exist (dev/test)
_FALLBACK = "/tmp/tablescope_last_activity.json"


def update_activity(
    user_id: int | None = None,
    tenant_id: int | None = None,
    project_id: int | None = None,
) -> None:
    """Write last activity timestamp for idle shutdown monitor."""
    path = ACTIVITY_FILE if os.path.isdir(os.path.dirname(ACTIVITY_FILE)) else _FALLBACK
    data = {
        "last_activity_utc": datetime.now(timezone.utc).isoformat(),
        "last_request_user_id": user_id,
        "last_request_tenant_id": tenant_id,
        "last_request_project_id": project_id,
    }
    try:
        with open(path, "w") as f:
            json.dump(data, f)
    except OSError:
        pass
