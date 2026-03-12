from cost_optimizer import analyze_live_finops, SavingsCategory

def test_analyze_live_finops_azure():
    live_schema = {
        "metadata": {
            "provider": "Azure"
        },
        "resources": [
            {
                "id": "1",
                "name": "disk1",
                "type": "microsoft.compute/disks",
                "attributes": {
                    "diskState": "Unattached"
                }
            },
            {
                "id": "2",
                "name": "disk2",
                "type": "microsoft.compute/disks",
                "attributes": {
                    "diskState": "Attached"
                }
            },
            {
                "id": "3",
                "name": "ip1",
                "type": "microsoft.network/publicipaddresses",
                "attributes": {}
            }
        ]
    }
    
    result = analyze_live_finops(live_schema)
    
    assert result["provider"] == "azure"
    assert result["total_optimizations"] == 2
    
    opts = result["optimizations"]
    assert any("disk1" in o["services_affected"] for o in opts)
    assert not any("disk2" in o["services_affected"] for o in opts)
    
    assert result["by_category"][SavingsCategory.STORAGE_TIERING.value]
    assert result["by_category"][SavingsCategory.RIGHT_SIZING.value]
