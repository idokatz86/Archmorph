"""
Chat routes — AI assistant with GitHub issue creation.
"""

from fastapi import APIRouter, Request, Depends
from pydantic import Field
from strict_models import StrictBaseModel
from typing import Optional

from routers.shared import limiter, verify_api_key
from chatbot import process_chat_message, get_chat_history, clear_chat_session
from usage_metrics import record_event

import asyncio

router = APIRouter()


class ChatMessage(StrictBaseModel):
    message: str = Field(..., min_length=1, max_length=5000)
    session_id: Optional[str] = Field(default="default", max_length=100)


@router.post("/api/chat")
@limiter.limit("15/minute")
async def chat(request: Request, msg: ChatMessage, _auth=Depends(verify_api_key)):
    """Process a chat message and return bot response. Can create GitHub issues."""
    record_event("chat_messages", {"session_id": msg.session_id})
    result = await asyncio.to_thread(process_chat_message, msg.session_id, msg.message)
    if result.get("action") == "issue_created":
        record_event("github_issues_created", result.get("data", {}))
    return result


@router.get("/api/chat/history/{session_id}")
@limiter.limit("30/minute")
async def chat_history(request: Request, session_id: str, _auth=Depends(verify_api_key)):
    """Get chat history for a session."""
    return {"session_id": session_id, "messages": get_chat_history(session_id)}


@router.delete("/api/chat/{session_id}")
@limiter.limit("10/minute")
async def chat_clear(request: Request, session_id: str, _auth=Depends(verify_api_key)):
    """Clear a chat session."""
    cleared = clear_chat_session(session_id)
    return {"cleared": cleared}
