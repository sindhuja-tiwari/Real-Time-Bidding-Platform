"""Backend for providers with an OpenAI-compatible chat API and a free tier.

Lets the investigator and the log-only baseline run without an Anthropic key.
The loop keeps its messages in one shape (content blocks with ``tool_use`` and
``tool_result``); this module translates them to chat-completions messages on
every request.

Default model names change often; pass ``--model`` to pick another.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

import httpx

from evidenceops.agent.loop import ToolUse, Turn

PROVIDERS: Dict[str, Dict[str, str]] = {
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "key_env": "GEMINI_API_KEY",
        "model": "gemini-2.5-flash",
        "key_url": "https://aistudio.google.com/apikey",
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "key_env": "GROQ_API_KEY",
        "model": "llama-3.3-70b-versatile",
        "key_url": "https://console.groq.com/keys",
    },
}
MAX_TOKENS = 8_000


def to_chat_messages(system: str, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = [{"role": "system", "content": system}]
    for m in messages:
        content = m["content"]
        if isinstance(content, str):
            out.append({"role": m["role"], "content": content})
        elif m["role"] == "assistant":
            text = "".join(b["text"] for b in content if b["type"] == "text")
            calls = [
                {"id": b["id"], "type": "function", "function": {"name": b["name"], "arguments": json.dumps(b["input"])}}
                for b in content if b["type"] == "tool_use"
            ]
            msg: Dict[str, Any] = {"role": "assistant", "content": text or None}
            if calls:
                msg["tool_calls"] = calls
            out.append(msg)
        else:
            for b in content:
                out.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": b["content"]})
    return out


def to_chat_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
        for t in tools
    ]


class OpenAICompatModel:
    def __init__(self, provider: str, model: Optional[str] = None, client: Optional[httpx.Client] = None):
        if provider not in PROVIDERS:
            raise ValueError(f"unknown provider {provider!r}")
        cfg = PROVIDERS[provider]
        key = os.environ.get(cfg["key_env"], "")
        if not key and client is None:
            raise SystemExit(f"No {provider} key found. Create one at {cfg['key_url']} and export it as {cfg['key_env']}.")
        self.provider = provider
        self.name = model or cfg["model"]
        self.client = client or httpx.Client(
            base_url=cfg["base_url"], headers={"Authorization": f"Bearer {key}"}, timeout=120.0
        )

    def _post(self, body: Dict[str, Any]) -> Dict[str, Any]:
        response = self.client.post("/chat/completions", json={"model": self.name, "max_tokens": MAX_TOKENS, **body})
        if response.status_code == 401:
            raise SystemExit(f"{self.provider} rejected the API key (401).")
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _usage(data: Dict[str, Any]) -> Dict[str, int]:
        u = data.get("usage") or {}
        return {"input_tokens": int(u.get("prompt_tokens") or 0), "output_tokens": int(u.get("completion_tokens") or 0)}

    def respond(self, system: str, tools: List[Dict[str, Any]], messages: List[Dict[str, Any]]) -> Turn:
        data = self._post({"messages": to_chat_messages(system, messages), "tools": to_chat_tools(tools)})
        choice = data["choices"][0]
        msg = choice["message"]
        content: List[Dict[str, Any]] = []
        if msg.get("content"):
            content.append({"type": "text", "text": msg["content"]})
        uses = []
        for call in msg.get("tool_calls") or []:
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
            except ValueError:
                args = {"unparseable_arguments": call["function"].get("arguments")}
            if not isinstance(args, dict):
                args = {"unparseable_arguments": args}
            uses.append(ToolUse(call["id"], call["function"]["name"], args))
            content.append({"type": "tool_use", "id": call["id"], "name": call["function"]["name"], "input": args})
        stop = {"length": "max_tokens", "content_filter": "refusal"}.get(choice.get("finish_reason"), "tool_use" if uses else "end_turn")
        return Turn(content=content, tool_uses=uses, stop_reason=stop, text=msg.get("content") or "",
                    usage=self._usage(data), cost_usd=0.0, model=data.get("model") or self.name)

    def complete_json(self, system: str, prompt: str, schema: Dict[str, Any]) -> Dict[str, Any]:
        """One request that must answer with JSON matching ``schema``."""
        data = self._post({
            "messages": [
                {"role": "system", "content": system + "\nAnswer with one JSON object matching this schema:\n" + json.dumps(schema)},
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
        })
        choice = data["choices"][0]
        return {
            "stop_reason": {"length": "max_tokens", "content_filter": "refusal"}.get(choice.get("finish_reason"), "end_turn"),
            "text": choice["message"].get("content") or "",
            "usage": self._usage(data),
            "cost_usd": 0.0,
            "model": data.get("model") or self.name,
        }
