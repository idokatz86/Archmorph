import os
import json
import time
import asyncio
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session

from models.agent import Agent
from models.execution import Execution
from database import SessionLocal
from services.model_router import ModelRouter

class AgentRunner:
    """
    Executes an AI Agent run asynchronously.
    """
    def __init__(self, execution_id: str):
        self.execution_id = execution_id
        self.router = ModelRouter(SessionLocal(), "org")
        
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
            
            model_client = self.router.route("default")
            
            # Setup Tools (basic mock for now)
            formatted_tools = []
            if agent.tools:
                for tool in agent.tools:
                    # Actually convert or just pass-through OpenAI tools format
                    # Assumes agent.tools is stored as OpenAI tool specs
                    formatted_tools.append(tool)
                    
            start_time = time.time()
            
            # Execute Model via abstracted Client
            response = await model_client.chat(
                messages=llm_messages,
                tools=formatted_tools if formatted_tools else None,
                temperature=agent.model_config_data.get("temperature", 0.7) if agent.model_config_data else 0.7
            )
            
            # Simple tool calling execution loop
            message = response.choices[0].message
            content = message.content or ""
            
            # Check if it called a tool
            if getattr(message, 'tool_calls', None):
                for tool_call in message.tool_calls:
                    # Fake execution of tool
                    func_name = tool_call.function.name
                    func_args = tool_call.function.arguments
                    # Append message
                    llm_messages.append(message)
                    llm_messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": func_name,
                        "content": json.dumps({"status": "success", "result": f"Executed {func_name} with {func_args}"})
                    })
                
                # Second call to get final response
                response = await model_client.chat(
                    messages=llm_messages,
                    temperature=agent.model_config_data.get("temperature", 0.7) if agent.model_config_data else 0.7
                )
                message = response.choices[0].message
                content = message.content or ""

            end_time = time.time()
            
            duration_ms = int((end_time - start_time) * 1000)
            
            prompt_tokens = response.usage.prompt_tokens if hasattr(response, 'usage') and response.usage else 0
            completion_tokens = response.usage.completion_tokens if hasattr(response, 'usage') and response.usage else 0
            
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
