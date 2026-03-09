import logging
import re
from typing import Dict, Any, List
from sqlalchemy.orm import Session
from fastapi import HTTPException

from models.policy import AgentPolicy, AgentPolicyBinding

logger = logging.getLogger(__name__)

class PolicyEngine:
    """
    Evaluates inputs, outputs, and tool usage against active policies.
    """
    def __init__(self, db: Session, org_id: str, agent_id: str):
        self.db = db
        self.org_id = org_id
        self.agent_id = agent_id

    def get_active_policies(self, policy_type: str = None) -> List[AgentPolicy]:
        """Fetch active policies bound to this agent or global to the org."""
        query = self.db.query(AgentPolicy).join(
            AgentPolicyBinding, AgentPolicy.id == AgentPolicyBinding.policy_id
        ).filter(
            AgentPolicyBinding.agent_id == self.agent_id,
            AgentPolicy.organization_id == self.org_id,
            AgentPolicy.is_active == True
        )
        if policy_type:
            query = query.filter(AgentPolicy.policy_type == policy_type)
        return query.all()

    def evaluate_input(self, messages: List[Dict[str, Any]]):
        """
        Evaluate user input against input policies 
        (e.g., regex blocklists, prompt injection heuristics).
        Raises HTTPException if blocked.
        """
        policies = self.get_active_policies("input")
        if not policies:
            return

        text_to_check = "\n".join([m.get("content", "") for m in messages if m.get("role") == "user"])

        for policy in policies:
            rules = policy.rules or {}
            blocklist = rules.get("blocklist_regex", [])
            for pattern in blocklist:
                if re.search(pattern, text_to_check, re.IGNORECASE):
                    if policy.enforcement_level == "block":
                        raise HTTPException(status_code=400, detail=f"Input blocked by policy: {policy.name}")
                    else:
                        logger.warning(f"[POLICY FLAG] Agent {self.agent_id} flagged input on policy {policy.name}")

    def evaluate_output(self, content: str) -> str:
        """
        Evaluate agent output against output policies (e.g. secret redaction).
        Returns the sanitized output.
        """
        policies = self.get_active_policies("output")
        if not policies:
            return content

        sanitized = content
        for policy in policies:
            rules = policy.rules or {}
            redact_list = rules.get("redact_patterns", [])
            for pattern in redact_list:
                sanitized = re.sub(pattern, "[REDACTED]", sanitized, flags=re.IGNORECASE)
                
            if "block_code" in rules and rules["block_code"]:
                if "```" in sanitized:
                    if policy.enforcement_level == "block":
                        raise HTTPException(status_code=400, detail=f"Output blocked by policy: {policy.name}")

        return sanitized

    def evaluate_tool_access(self, tool_name: str):
        """
        Evaluate if agent is allowed to use a given tool.
        """
        policies = self.get_active_policies("tool")
        if not policies:
            return True

        for policy in policies:
            rules = policy.rules or {}
            allowlist = rules.get("allowlist", [])
            blocklist = rules.get("blocklist", [])

            if blocklist and tool_name in blocklist:
                if policy.enforcement_level == "block":
                    raise HTTPException(status_code=403, detail=f"Tool {tool_name} is blocked by policy {policy.name}")
            
            if allowlist and tool_name not in allowlist:
                 if policy.enforcement_level == "block":
                    raise HTTPException(status_code=403, detail=f"Tool {tool_name} is not in allowlist for policy {policy.name}")
                    
        return True
