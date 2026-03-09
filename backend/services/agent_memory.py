import logging
from typing import List, Dict, Any
from sqlalchemy.orm import Session

from models.agent import Agent
from models.memory import AgentMemoryDocument, AgentEpisodicMemory, AgentEntityMemory
import tiktoken

logger = logging.getLogger(__name__)

class MemoryManager:
    """
    Handles working memory limits (Short-Term Memory)
    and semantic indexing limits (Long-Term Memory).
    """

    def __init__(self, db: Session, agent_id: str):
        self.db = db
        self.agent_id = agent_id
        
        # We can dynamically set this based on model
        self.encoding = tiktoken.get_encoding("cl100k_base")

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count for safety."""
        if not text:
            return 0
        try:
            return len(self.encoding.encode(text))
        except Exception:
            return len(text) // 4 # fallback

    def prepare_short_term_buffer(self, messages: List[Dict[str, Any]], max_tokens: int = 4000) -> List[Dict[str, Any]]:
        """
        Token-aware windowing.
        Returns messages that fit in the max_tokens window, keeping the most recent.
        """
        if not messages:
            return []

        # Keep system prompt at the very beginning always
        system_msgs = [m for m in messages if m.get("role") == "system"]
        chat_msgs = [m for m in messages if m.get("role") != "system"]

        sys_tokens = sum(self.estimate_tokens(m.get("content", "")) for m in system_msgs)
        budget = max_tokens - sys_tokens

        # Go backwards, keep adding until budget is full
        kept_chat = []
        for msg in reversed(chat_msgs):
            tokens = self.estimate_tokens(msg.get("content", ""))
            if budget - tokens > 0:
                kept_chat.insert(0, msg)
                budget -= tokens
            else:
                break
                
        # If we truncated some, maybe add a summary message? (Future enhancement)
        
        return system_msgs + kept_chat

    def save_episodic_memory(self, execution_id: str, summary: str, importance: float = 1.0, tags: List[str] = None):
        """
        Store an episodic memory for future retrieval.
        """
        memory = AgentEpisodicMemory(
            agent_id=self.agent_id,
            execution_id=execution_id,
            summary=summary,
            importance_score=importance,
            tags=tags or []
        )
        self.db.add(memory)
        self.db.commit()
        return memory

    def save_entity(self, name: str, entity_type: str, attributes: Dict[str, Any]):
        """
        Store an extracted entity.
        """
        entity = self.db.query(AgentEntityMemory).filter(
            AgentEntityMemory.agent_id == self.agent_id,
            AgentEntityMemory.entity_name == name
        ).first()

        if entity:
            # merge attributes
            existing_attrs = entity.attributes or {}
            existing_attrs.update(attributes)
            entity.attributes = existing_attrs
        else:
            entity = AgentEntityMemory(
                agent_id=self.agent_id,
                entity_name=name,
                entity_type=entity_type,
                attributes=attributes
            )
            self.db.add(entity)
            
        self.db.commit()
        return entity

    def retrieve_relevant_context(self, current_query: str) -> str:
        """
        Given the current_query, look up matching entities and episodic memories.
        Right now, a simple mock, eventually wired to Qdrant/PGVector.
        """
        # Pseudo vector search mock
        episodes = self.db.query(AgentEpisodicMemory).filter(AgentEpisodicMemory.agent_id == self.agent_id).limit(5).all()
        entities = self.db.query(AgentEntityMemory).filter(AgentEntityMemory.agent_id == self.agent_id).limit(5).all()
        
        context_parts = []
        if episodes:
            context_parts.append("### Previous Related Episodes ###")
            for ep in episodes:
                context_parts.append(f"- {ep.summary}")
                
        if entities:
            context_parts.append("### Relevant Entities ###")
            for ent in entities:
                context_parts.append(f"- {ent.entity_name} ({ent.entity_type}): {ent.attributes}")
                
        return "\n".join(context_parts)
