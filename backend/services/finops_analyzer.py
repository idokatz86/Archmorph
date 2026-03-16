import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

SERVICE_COST_MAP = {
    "app_service": 54.75,
    "kubernetes_cluster": 73.00,
    "aks_node": 73.00,
    "sql_database": 14.60,
    "postgres_flexible": 35.00,
    "storage_account": 20.80,
    "virtual_network": 0.00,
    "api_management": 48.00,
    "redis_cache": 32.00,
    "function_app": 0.00,
    "default_vm": 73.00
}

def calculate_costs(topology: Dict[str, Any]) -> Dict[str, Any]:
    elements = topology.get("elements", [])
    if not elements:
        if isinstance(topology, list):
            elements = topology
            
    total_monthly_usd = 0.0
    line_items = []
    
    for element in elements:
        res_type = element.get('type', '').lower()
        res_name = element.get('name', 'Unknown Resource')
        
        estimated_cost = 0.0
        applied_sku = "Consumption / Free"
        
        if 'app' in res_type and 'service' in res_type:
            estimated_cost = SERVICE_COST_MAP["app_service"]
            applied_sku = "Basic B1"
        elif 'kubernetes' in res_type or 'aks' in res_type:
            estimated_cost = SERVICE_COST_MAP["kubernetes_cluster"] + (SERVICE_COST_MAP["aks_node"] * 2)
            applied_sku = "Standard (SLA) + 2x Standard_D2s_v3"
        elif 'sql' in res_type:
            estimated_cost = SERVICE_COST_MAP["sql_database"]
            applied_sku = "Basic, 5 DTU"
        elif 'postgres' in res_type:
            estimated_cost = SERVICE_COST_MAP["postgres_flexible"]
            applied_sku = "Burstable, B1ms"
        elif 'storage' in res_type:
            estimated_cost = SERVICE_COST_MAP["storage_account"]
            applied_sku = "Standard LRS (Estimated 1TB)"
        elif 'api' in res_type and 'management' in res_type:
            estimated_cost = SERVICE_COST_MAP["api_management"]
            applied_sku = "Developer Tier"
        elif 'redis' in res_type:
            estimated_cost = SERVICE_COST_MAP["redis_cache"]
            applied_sku = "Basic C0"
        elif 'vm' in res_type or 'machine' in res_type or 'compute' in res_type:
            count = element.get('config', {}).get('instance_count', 1)
            try:
                count = int(count)
            except:
                count = 1
            estimated_cost = SERVICE_COST_MAP["default_vm"] * count
            applied_sku = f"{count}x Standard_D2s_v3"
            
        line_items.append({
            "resource": res_name,
            "type": res_type,
            "monthly_cost_usd": round(estimated_cost, 2),
            "assumed_sku": applied_sku
        })
        
        total_monthly_usd += estimated_cost
        
    return {
        "currency": "USD",
        "total_monthly_estimate": round(total_monthly_usd, 2),
        "total_annual_estimate": round(total_monthly_usd * 12, 2),
        "breakdown": line_items,
        "disclaimer": "Prices are estimates based on standard regional rates and may vary based on exact usage, egress, and active region."
    }
