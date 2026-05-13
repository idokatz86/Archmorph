import json
import os
import sys
from unittest.mock import patch


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import usage_metrics


def test_load_metrics_can_skip_blob_for_startup(tmp_path):
    metrics_file = tmp_path / "usage_metrics.json"
    metrics_file.write_text(
        json.dumps({"counters": {}, "daily": {}, "recent_events": []}),
        encoding="utf-8",
    )

    with patch("usage_metrics.METRICS_FILE", str(metrics_file)), \
         patch("usage_metrics._get_blob_client") as get_blob:
        usage_metrics._load_metrics(prefer_blob=False)

    get_blob.assert_not_called()
    assert "counters" in usage_metrics._metrics