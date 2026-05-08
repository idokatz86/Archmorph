import asyncio
import time

from models.agent import Agent
from models.execution import Execution
from database import SessionLocal
from services.model_router import ModelRouter
from services.tool_registry import tool_registry


class AgentRunner:
    """
    Executes an AI Agent run asynchronously.
    """
    def __init__(self, execution_id: str):
        self.execution_id = execution_id

    async def run(self):
        # ── Phase 1: load execution + agent, then release DB ──
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

            # Snapshot all data needed for model call — then close DB
            messages = execution.input_data.get("messages", [])
            session_token = execution.input_data.get("session_token")
            sys_msg = (
                agent.model_config_data.get("system_prompt", "You are a helpful assistant.")
                if agent.model_config_data
                else "You are a helpful assistant."
            )
            temperature = (
                agent.model_config_data.get("temperature", 0.7)
                if agent.model_config_data
                else 0.7
            )
            agent_tools = agent.tools or []
        finally:
            db.close()  # release before any model call

        # ── Phase 2: model calls (no DB session held) ──
        db2 = SessionLocal()
        try:
            model_client = ModelRouter(db2, "org").route("default")
        finally:
            db2.close()

        llm_messages = [{"role": "system", "content": sys_msg}] + messages

        # Setup Tools
        formatted_tools = list(tool_registry.get_schemas())
        for tool in agent_tools:
            existing_names = [t.get("function", {}).get("name") for t in formatted_tools]
            if tool.get("function", {}).get("name") not in existing_names:
                formatted_tools.append(tool)

        start_time = time.time()

        try:
            # Execute Model via abstracted Client
            response = await model_client.chat(
                messages=llm_messages,
                tools=formatted_tools if formatted_tools else None,
                temperature=temperature,
            )

            # Simple tool calling execution loop
            message = response.choices[0].message
            content = message.content or ""

            # Check if it called a tool — execute all tool calls concurrently
            if getattr(message, 'tool_calls', None):
                async def _run_tool(tool_call):
                    return await tool_registry.execute(
                        tool_call.function.name,
                        tool_call.function.arguments,
                        session_token=session_token,
                    )

                tool_results = await asyncio.gather(
                    *[_run_tool(tc) for tc in message.tool_calls],
                    return_exceptions=True,
                )

                llm_messages.append(message)
                for tc, result_json in zip(message.tool_calls, tool_results):
                    if isinstance(result_json, Exception):
                        result_json = f'{{"error": "{tc.function.name} failed"}}'
                    llm_messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": tc.function.name,
                        "content": result_json,
                    })

                # Second call to get final response
                response = await model_client.chat(
                    messages=llm_messages,
                    temperature=temperature,
                )
                message = response.choices[0].message
                content = message.content or ""

            end_time = time.time()
            duration_ms = int((end_time - start_time) * 1000)

            prompt_tokens = response.usage.prompt_tokens if hasattr(response, 'usage') and response.usage else 0
            completion_tokens = response.usage.completion_tokens if hasattr(response, 'usage') and response.usage else 0

            # ── Phase 3: write result back to DB ──
            db3 = SessionLocal()
            try:
                execution = db3.query(Execution).filter(Execution.id == self.execution_id).first()
                if execution:
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
                            "tokens": prompt_tokens + completion_tokens,
                        }
                    ]
                    db3.commit()
            finally:
                db3.close()

            print(f"[AgentRunner] Finished execution {self.execution_id}")

        except Exception as e:
            db4 = SessionLocal()
            try:
                execution = db4.query(Execution).filter(Execution.id == self.execution_id).first()
                if execution:
                    execution.status = "failed"
                    execution.error_message = str(e)
                    db4.commit()
            finally:
                db4.close()
            print(f"[AgentRunner] Failed execution {self.execution_id}: {e}")
