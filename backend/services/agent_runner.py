import os
import json
import time
import asyncio
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session

from models.agent import Agent
from models.execution import Execution
from database import SessionLocal
from openai_client import AsyncOpenAIClient

class AgentRunner:
    """
    Executes an AI Agent run asynchronously.
    """
    def __init__(self, execution_id: str):
        self.execution_id = execution_id
        self.client = AsyncOpenAIClient()
        
    async def run(self):
        db = SessionLocal()
        try:
            execution = db.query(Execution).filter(Execution.id == self.execution_id).first()
            if not execution:
                print(f"[AgentRunner] Execution {self.execution_id} not found.")
                return
                
            execution.status = "running"
            db.commit()
            
            agent = db.query(Agent).filter(Agent.id == execution.agent_id).first()
            if not agent:
                execution.status = "failed"
                execution.error_message = "Agent not found"
                db.commit()
                return

            messages = execution.input_data.get("messages", [])
            
            # Inject System Prompt
            sys_msg = agent.model_config_data.get("system_prompt", "You are a helpful assistant.") if agent.model_config_data else "You are a helpful assistant."
            llm_messages = [{"role": "system", "content": sys_msg}] + messages
            
            # Setup Tools (basic mock for now)
            tools = []
            if agent.tools:
                for tool in agent.tools:
                    # e.g., tool could be {"type": "function", "function": {"name": "...", "description": "..."}}
                    pass # Placeholder: parse agent.tools locally
                    
            start_time = time.time()
            
            # Execute Model via OpenAI Async API
            response = await self.client.client.chat.completions.create(
                model=os.getenv("OPENAI_MODEL", "gpt-4o"),
                messages=llm_messages,
                temperature=agent.model_config_data.get("temperature", 0.7) if agent.model_config_data else 0.7
            )
            
            end_time = time.time()
            
            duration_ms = int((end_time - start_time) * 1000)
            
            content = response.choices[0].message.content
            prompt_tokens = response.usage.prompt_tokens if response.usage else 0
            completion_tokens = response.usage.completion_tokens if response.usage else 0
            
            # Update Execution
            execution.status = "completed"
            execution.output_data = {"message": content}
            execution.prompt_tokens = prompt_tokens
            execution.completion_tokens = completion_tokens
            execution.total_tokens = prompt_tokens + completion_tokens
            execution.duration_ms = duration_ms
            execution.steps = [
                {
                    "type": "llm_call",
                    "duration": duration_ms,
                    "tokens": prompt_tokens + completion_tokens
                }
            ]
            
            db.commit()
            print(f"[AgentRunner] Finished execution {self.execution_id}")

        except Exception as e:
            db.rollback()
            execution = db.query(Execution).filter(Execution.id == self.execution_id).first()
            if execution:
                execution.status = "failed"
                execution.error_message = str(e)
                db.commit()
            print(f"[AgentRunner] Failed execution {self.execution_id}: {e}")
        finally:
            db.close()
