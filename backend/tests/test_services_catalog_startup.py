import json
import os
import sys
from unittest.mock import patch


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import services


def test_catalog_reload_can_skip_blob_for_startup(tmp_path):
    discovered_file = tmp_path / "discovered_services.json"
    discovered_file.write_text(
        json.dumps({"aws": [], "azure": [], "gcp": []}),
        encoding="utf-8",
    )

    with patch("services._DISCOVERED_FILE", discovered_file), \
         patch("service_updater._load_discovered_from_blob") as load_blob:
        counts = services.reload(prefer_blob=False)

    load_blob.assert_not_called()
    assert counts["aws"] >= 1
    assert counts["azure"] >= 1
    assert counts["gcp"] >= 1