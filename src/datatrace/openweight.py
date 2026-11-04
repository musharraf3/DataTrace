"""Chat Completions adapter so the same agent can run on open-weight Meta models.

Partner hosts (Baseten, Fireworks, Modal) serve Muse open-weight models behind OpenAI-compatible
/chat/completions endpoints. This client exposes the same complete() interface as MetaClient and
returns Responses-shaped dicts, so investigate_meta runs unchanged. Conversation state that the
Responses API keeps server-side (previous_response_id) is kept locally here.

Configure in .env (never commit keys):
  DATATRACE_PROVIDER=openweight
  OPENWEIGHT_BASE_URL=https://inference.baseten.co/v1     (or Fireworks / Modal / api.meta.ai)
  OPENWEIGHT_API_KEY=...
  OPENWEIGHT_MODEL=meta-models/muse-spark-open-1026
"""

import json
import os
import urllib.parse
import urllib.request
import uuid

from .meta import BASELINE_NOTE, SYSTEM, TOOLS, MetaAPIError, MetaClient

# Credentials are only ever sent to these hosts (exact match or listed suffix), over HTTPS.
ALLOWED_HOSTS = {"api.meta.ai", "inference.baseten.co", "bridge.baseten.co", "api.fireworks.ai"}
ALLOWED_SUFFIXES = (".baseten.co", ".modal.run", ".fireworks.ai")


def _check_url(url):
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or ""
    if parsed.scheme != "https" or not (host in ALLOWED_HOSTS or host.endswith(ALLOWED_SUFFIXES)):
        raise MetaAPIError("OPENWEIGHT_BASE_URL must be https on Meta, Baseten, Fireworks or Modal.")
    return url.rstrip("/")


def _chat_tools():
    return [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                              "parameters": t["parameters"]}} for t in TOOLS]


def _content(parts):
    if isinstance(parts, str):
        return parts
    out = []
    for part in parts:
        if part.get("type") == "input_text":
            out.append({"type": "text", "text": part["text"]})
        elif part.get("type") == "input_image":
            out.append({"type": "image_url", "image_url": {"url": part["image_url"]}})
    return out


class ChatCompletionsClient(MetaClient):
    """Drop-in client for OpenAI-compatible /chat/completions endpoints."""

    def __init__(self, *, base_url=None, key=None, model=None, review_model=None):
        self.key = (key or os.environ.get("OPENWEIGHT_API_KEY", "")).strip()
        self.base_url = _check_url(base_url or os.environ.get("OPENWEIGHT_BASE_URL", ""))
        self.model = model or os.environ.get("OPENWEIGHT_MODEL", "")
        self.review_model = review_model or os.environ.get("OPENWEIGHT_REVIEW_MODEL") or self.model
        self.effort = os.environ.get("META_REASONING_EFFORT", "medium")
        self.provider = urllib.parse.urlparse(self.base_url).hostname
        if not self.key or not self.model:
            raise MetaAPIError("Set OPENWEIGHT_API_KEY and OPENWEIGHT_MODEL in your local .env.")
        self._history = {}

    def complete(self, *, inputs, previous_response_id=None, tools_enabled=True, instructions=None,
                 model=None, effort=None, text_format=None, max_output_tokens=8000):
        if instructions is None:
            instructions = SYSTEM if tools_enabled else SYSTEM + BASELINE_NOTE
        if previous_response_id:
            if previous_response_id not in self._history:
                raise MetaAPIError("Unknown conversation for this open-weight session.")
            messages = list(self._history[previous_response_id])
            messages[0] = {"role": "system", "content": instructions}
        else:
            messages = [{"role": "system", "content": instructions}]
        if isinstance(inputs, str):
            messages.append({"role": "user", "content": inputs})
        else:
            for item in inputs:
                if item.get("type") == "function_call_output":
                    messages.append({"role": "tool", "tool_call_id": item["call_id"], "content": item["output"]})
                elif item.get("role") == "user":
                    messages.append({"role": "user", "content": _content(item["content"])})
        body = {"model": model or self.model, "messages": messages, "max_tokens": max_output_tokens}
        if tools_enabled:
            body.update({"tools": _chat_tools(), "parallel_tool_calls": True})
        if text_format:
            body["response_format"] = {"type": "json_schema", "json_schema": {
                "name": text_format["name"], "schema": text_format["schema"], "strict": text_format.get("strict", True)}}
        data = json.dumps(body).encode()
        if len(data) > 12000000:
            raise MetaAPIError("Incident context is too large for this prototype.")
        request = urllib.request.Request(self.base_url + "/chat/completions", data=data,
                                         headers={"Authorization": "Bearer " + self.key, "Content-Type": "application/json"})
        payload = self._send(request, 180)
        try:
            message = payload["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            raise MetaAPIError("Malformed chat completion response.") from None
        output = []
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            output.append({"type": "function_call", "call_id": call.get("id"), "name": function.get("name"),
                           "arguments": function.get("arguments", "")})
        if message.get("content"):
            output.append({"type": "message", "content": [{"type": "output_text", "text": message["content"]}]})
        response_id = "chat_" + uuid.uuid4().hex
        assistant = {"role": "assistant", "content": message.get("content") or ""}
        if message.get("tool_calls"):
            assistant["tool_calls"] = message["tool_calls"]
        self._history[response_id] = messages + [assistant]
        usage = payload.get("usage") or {}
        return {"id": response_id, "status": "completed", "output": output, "model": payload.get("model"),
                "usage": {"input_tokens": int(usage.get("prompt_tokens", 0) or 0),
                          "output_tokens": int(usage.get("completion_tokens", 0) or 0)}}

    def transcribe(self, wav_bytes):
        raise MetaAPIError("Voice intake uses the Meta-hosted muse-voice-transcribe-1.0 model.")


def make_agent_client():
    """Hosted Meta (default) or an open-weight provider, chosen by DATATRACE_PROVIDER."""
    if os.environ.get("DATATRACE_PROVIDER", "meta").lower() == "openweight":
        return ChatCompletionsClient()
    return MetaClient()
