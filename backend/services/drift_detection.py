from datetime import datetime, timezone
from typing import Any, Dict, List

import logging

logger = logging.getLogger(__name__)

class DriftDetector:
    def __init__(self):
        pass

    def _node_key(self, node: Dict[str, Any]) -> str:
        return str(
            node.get("id")
            or node.get("resource_id")
            or node.get("resourceId")
            or node.get("name")
            or node.get("label")
            or ""
        ).strip()

    def _node_type(self, node: Dict[str, Any]) -> str:
        return str(
            node.get("type")
            or node.get("resource_type")
            or node.get("resourceType")
            or node.get("service")
            or node.get("kind")
            or ""
        ).strip().lower()

    def _tracked_config(self, node: Dict[str, Any]) -> Dict[str, Any]:
        tracked = {}
        for key in (
            "sku",
            "tier",
            "region",
            "location",
            "tags",
            "public_access",
            "encryption",
            "replication",
        ):
            if key in node:
                tracked[key] = node[key]
        return tracked

    def _build_summary(self, findings: List[Dict[str, Any]]) -> Dict[str, Any]:
        counts = {
            "green": sum(1 for finding in findings if finding["status"] == "green"),
            "yellow": sum(1 for finding in findings if finding["status"] == "yellow"),
            "red": sum(1 for finding in findings if finding["status"] == "red"),
            "grey": sum(1 for finding in findings if finding["status"] == "grey"),
        }
        total = len(findings)
        blocking = counts["red"] + counts["grey"]
        if total == 0:
            score = 1.0
        else:
            score = max(0.0, (counts["green"] + counts["yellow"] * 0.5) / total)
        return {
            "total_findings": total,
            "matched": counts["green"],
            "modified": counts["yellow"],
            "shadow": counts["red"],
            "missing": counts["grey"],
            "blocking_findings": blocking,
            "status": (
                "healthy"
                if blocking == 0 and counts["yellow"] == 0
                else "warning" if blocking == 0 else "attention_required"
            ),
            "score": round(score, 2),
        }

    def compare_nodes(
        self,
        designed_nodes: List[Dict[str, Any]],
        live_nodes: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        designed_map = {self._node_key(n): n for n in designed_nodes if self._node_key(n)}
        live_map = {self._node_key(n): n for n in live_nodes if self._node_key(n)}
        
        drift_results = []
        
        for node_id, d_node in designed_map.items():
            if node_id in live_map:
                l_node = live_map[node_id]
                d_type = self._node_type(d_node)
                l_type = self._node_type(l_node)
                if d_type != l_type:
                    drift_results.append({
                        "id": node_id,
                        "status": "yellow",
                        "message": f"Modified type: {d_type} -> {l_type}",
                        "designed_data": d_node,
                        "live_data": l_node,
                        "recommendation": "Confirm the live resource type or update the design baseline.",
                    })
                elif self._tracked_config(d_node) != self._tracked_config(l_node):
                    drift_results.append({
                        "id": node_id,
                        "status": "yellow",
                        "message": "Configuration differs from baseline",
                        "designed_data": d_node,
                        "live_data": l_node,
                        "recommendation": "Review the tracked settings and reconcile the diagram or IaC state.",
                    })
                else:
                    drift_results.append({
                        "id": node_id,
                        "status": "green",
                        "message": "Matched",
                        "designed_data": d_node,
                        "live_data": l_node,
                        "recommendation": "No action required.",
                    })
            else:
                drift_results.append({
                    "id": node_id,
                    "status": "grey",
                    "message": "Missing in reality",
                    "designed_data": d_node,
                    "live_data": None,
                    "recommendation": "Deploy the missing resource or remove it from the intended architecture.",
                })
                
        for node_id, l_node in live_map.items():
            if node_id not in designed_map:
                drift_results.append({
                    "id": node_id,
                    "status": "red",
                    "message": "Shadow IT",
                    "designed_data": None,
                    "live_data": l_node,
                    "recommendation": "Investigate ownership and bring the resource under approved design governance.",
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
        summary = self._build_summary(node_drift)
        recommendations = [finding["recommendation"] for finding in node_drift if finding["status"] != "green"]
        
        return {
            "overall_score": summary["score"],
            "drift_counts": counts,
            "summary": summary,
            "detailed_findings": node_drift,
            "recommendations": recommendations,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
