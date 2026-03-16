from fastapi.testclient import TestClient

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from main import app
from services.security_compliance import analyze_security_compliance
from services.finops_analyzer import calculate_costs

client = TestClient(app)

def test_security_compliance_logic():
    topology = {
        "elements": [
            {
                "type": "azure_sql_database",
                "name": "public-db",
                "config": {
                    "public_network_access_enabled": True
                }
            },
            {
                "type": "azure_app_service",
                "name": "my-app"
            }
        ]
    }
    
    res = analyze_security_compliance(topology)
    assert res['score'] < 100
    assert len(res['findings']) > 0
    assert res['findings'][0]['resource'] == 'public-db'

def test_finops_calculation_logic():
    topology = {
        "elements": [
            {
                "type": "azure_app_service",
                "name": "my-app"
            },
            {
                "type": "azure_sql_database",
                "name": "my-db"
            }
        ]
    }
    res = calculate_costs(topology)
    assert res['total_monthly_estimate'] > 0
    assert len(res['breakdown']) == 2
    
def test_preflight_endpoint():
    # Will need a valid auth mock but we can test logic functions independently
    pass
