"""Shared coercion helpers for chat-API responses.

Several chat endpoints (e.g. ``/iac-chat``, ``/migration-chat``) ask GPT
JSON-mode for arrays of strings, but the model occasionally returns
objects (e.g. ``{"type": "add", "message": "Added VNet"}``). The
frontend renders these items directly in JSX, which crashes React with
error #31 ("Objects are not valid as a React child").

Centralising the coercion here keeps the contract consistent across
endpoints without coupling unrelated routers to ``iac_chat`` internals.
"""
from __future__ import annotations

import json
from typing import Any, List


def coerce_to_str_list(items: Any) -> List[str]:
    """Coerce a model-returned list to a flat list of strings.

    - Strings pass through.
    - Numbers/bools are stringified.
    - ``None`` items are dropped.
    - Dicts are mapped via known string keys
      (``message``, ``text``, ``name``, ``label``, ``value``,
      ``description``); if none match, the dict is JSON-serialised so
      the frontend never sees a raw object.
    - Anything else falls back to ``str(item)``.

    Non-list inputs return an empty list — defence-in-depth so a single
    misbehaving response cannot break the API contract.
    """
    if not isinstance(items, list):
        return []
    out: List[str] = []
    for item in items:
        if item is None:
            continue
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, (int, float, bool)):
            out.append(str(item))
        elif isinstance(item, dict):
            for key in ("message", "text", "name", "label", "value", "description"):
                val = item.get(key)
                if isinstance(val, str) and val:
                    out.append(val)
                    break
            else:
                # Last resort — serialize so the frontend never sees an object.
                out.append(json.dumps(item, ensure_ascii=False))
        else:
            out.append(str(item))
    return out
