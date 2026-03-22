"""
Archmorph Agent PaaS — Built-in Mock Tools (Issue #397).

Provides safe mock tool implementations for the AI Agent PoC:
  - web_search: returns templated search snippets
  - code_interpreter: returns mock code execution results

These tools are SAFE — no actual web requests or code execution.
Each tool includes its OpenAI function-calling schema definition.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# OpenAI Function Schemas (for function-calling API)
# ─────────────────────────────────────────────────────────────

WEB_SEARCH_SCHEMA: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the web for current information on a topic. Returns top search result snippets.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query to look up.",
                },
            },
            "required": ["query"],
        },
    },
}

CODE_INTERPRETER_SCHEMA: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "code_interpreter",
        "description": "Execute Python code and return the result. Use for calculations, data analysis, or generating outputs.",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "The Python code to execute.",
                },
            },
            "required": ["code"],
        },
    },
}

# Registry of all built-in tools keyed by function name
BUILTIN_TOOLS: Dict[str, Dict[str, Any]] = {
    "web_search": WEB_SEARCH_SCHEMA,
    "code_interpreter": CODE_INTERPRETER_SCHEMA,
}


# ─────────────────────────────────────────────────────────────
# Mock Tool Implementations
# ─────────────────────────────────────────────────────────────

def execute_web_search(query: str) -> str:
    """Return mock web search results for the given query.

    SAFE: No actual HTTP requests are made. Returns templated snippets.
    """
    logger.info("Mock web_search called with query: %s", query[:100])
    results = [
        {
            "title": f"Understanding {query} — Overview",
            "snippet": (
                f"A comprehensive guide to {query}. This topic covers key concepts, "
                f"best practices, and common patterns used in modern systems."
            ),
            "url": f"https://docs.example.com/{query.lower().replace(' ', '-')}",
        },
        {
            "title": f"{query} — Best Practices 2025",
            "snippet": (
                f"Industry experts recommend the following approaches for {query}: "
                f"start with clear requirements, iterate on design, and measure outcomes."
            ),
            "url": f"https://blog.example.com/{query.lower().replace(' ', '-')}-best-practices",
        },
        {
            "title": f"Common Pitfalls with {query}",
            "snippet": (
                f"When working with {query}, avoid these common mistakes: "
                f"over-engineering, premature optimization, and ignoring observability."
            ),
            "url": f"https://learn.example.com/pitfalls/{query.lower().replace(' ', '-')}",
        },
    ]
    return json.dumps({"results": results, "query": query, "result_count": len(results)})


def execute_code_interpreter(code: str) -> str:
    """Return a mock code execution result.

    SAFE: No actual code is executed. Returns a templated response
    based on the code content.
    """
    logger.info("Mock code_interpreter called (code length: %d chars)", len(code))

    # Detect common patterns and return appropriate mock results
    code_lower = code.lower()

    if "import" in code_lower and ("pandas" in code_lower or "numpy" in code_lower):
        output = (
            "Data analysis complete.\n"
            "Shape: (1000, 5)\n"
            "Columns: ['id', 'name', 'value', 'category', 'timestamp']\n"
            "Summary statistics computed successfully."
        )
    elif "print" in code_lower:
        output = "Hello, World!\n(mock output — actual code execution disabled for security)"
    elif "def " in code_lower or "class " in code_lower:
        output = "Function/class defined successfully. No runtime errors detected."
    elif any(op in code_lower for op in ["sum(", "len(", "max(", "min(", "+", "*"]):
        output = "Calculation result: 42\n(mock output — actual code execution disabled for security)"
    else:
        output = "Code executed successfully.\n(mock output — actual code execution disabled for security)"

    return json.dumps({
        "status": "success",
        "output": output,
        "execution_time_ms": 127,
    })


# Dispatcher: function name → handler
TOOL_EXECUTORS = {
    "web_search": lambda args: execute_web_search(args.get("query", "")),
    "code_interpreter": lambda args: execute_code_interpreter(args.get("code", "")),
}


def execute_tool(tool_name: str, arguments: Dict[str, Any]) -> str:
    """Execute a mock tool by name. Returns JSON string result."""
    executor = TOOL_EXECUTORS.get(tool_name)
    if executor is None:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})
    return executor(arguments)


def get_tool_schemas(tool_names: List[str]) -> List[Dict[str, Any]]:
    """Return OpenAI function schemas for the requested tool names."""
    return [BUILTIN_TOOLS[name] for name in tool_names if name in BUILTIN_TOOLS]
