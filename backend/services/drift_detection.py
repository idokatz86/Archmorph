import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

class DriftDetector:
    def __init__(self):
        pass

    def compare_nodes(self, designed_nodes: List[Dict[str, Any]], live_nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        designed_map = {n.get("id") or n.get("name"): n for n in designed_nodes}
        live_map = {n.get("id") or n.get("name"): n for n in live_nodes}
        
        drift_results = []
        
        for node_id, d_node in designed_map.items():
            if node_id in live_map:
                l_node = live_map[node_id]
                d_type = d_node.get("type", "")
                l_type = l_node.get("type", "")
                if d_type != l_type:
                    drift_results.append({
                        "id": node_id,
                        "status": "yellow",
                        "message": f"Modified type: {d_type} -> {l_type}",
                        "live_data": l_node
                    })
                else:
                    drift_results.append({
                        "id": node_id,
                        "status": "green",
                        "message": "Matched",
                        "live_data": l_node
                    })
            else:
                drift_results.append({
                    "id": node_id,
                    "status": "grey",
                    "message": "Missing in reality",
                    "live_data": None
                })
                
        for node_id, l_node in live_map.items():
            if node_id not in designed_map:
                drift_results.append({
                    "id": node_id,
                    "status": "red",
                    "message": "Shadow IT",
                    "live_data": l_node
                })
                
        return drift_results

    def detect_environmental_drift(self, designed_state: Dict[str, Any], live_state: Dict[str, Any]) -> Dict[str, Any]:
        designed_nodes = designed_state.get("nodes", [])
        live_nodes = live_state.get("nodes", [])
        
        node_drift = self.compare_nodes(designed_nodes, live_nodes)
        
        counts = {
            "green": sum(1 for d in node_drift if d["status"] == "green"),
            "yellow": sum(1 for d in node_drift if d["status"] == "yellow"),
            "red": sum(1 for d in node_drift if d["status"] == "red"),
            "grey": sum(1 for d in node_drift if d["status"] == "grey"),
        }
        
        return {
            "overall_score": counts["green"] / max(len(node_drift), 1),
            "drift_counts": counts,
            "detailed_findings": node_drift
        }
