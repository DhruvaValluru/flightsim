"""Alternative LLM providers for the compiler: same schema, same strict parse.

The compiler's correctness rails -- the RESPONSE_SCHEMA generated from the
spec's own fields, the strict ``_parse_payload``, the bit-identical regex
defaults and the unchanged validator -- are provider-independent by design
(SS2.14: nothing the LLM writes is evidence). This module lets the SAME
``compile_prompt_llm`` run against a model other than the Claude API: a
LOCAL Ollama model (free; no account, no key, no network) or any
OpenAI-compatible endpoint. Each client presents the anthropic-shaped
interface ``compile_prompt_llm`` already accepts through its ``client=``
injection point -- the seam the suite has always exercised with mocks.

Provider selection is env-driven and explicit:

* ``FLIGHTSIM_LLM=ollama`` -> local Ollama at ``OLLAMA_HOST`` (default
  ``http://127.0.0.1:11434``); model from ``FLIGHTSIM_LLM_MODEL``
  (default ``qwen2.5:7b``). Ollama's structured-output ``format`` field
  carries the SAME RESPONSE_SCHEMA, so the local model is grammar-
  constrained exactly as the Claude API is.
* ``FLIGHTSIM_LLM=openai`` -> any OpenAI-compatible endpoint
  (``OPENAI_BASE_URL``, ``OPENAI_API_KEY``, ``FLIGHTSIM_LLM_MODEL``) --
  Groq, Gemini's OpenAI layer, OpenRouter, a second Ollama, etc.
* neither set -> the Anthropic SDK path in ``llm_compiler`` (needs
  ``ANTHROPIC_API_KEY``).

An explicit ``FLIGHTSIM_LLM`` wins over a present ``ANTHROPIC_API_KEY``:
choosing a provider is a statement, not a fallback.

What a model swap changes and what it cannot: a weaker model produces
worse extractions and worse clarifying questions -- and the strict parser
rejects what it gets wrong, loudly, with the regex compiler as the stated
fallback. It cannot weaken a claim: the spec-review table, the validator
and the digest chain are downstream of ANY model. The model id (including
the provider's) is recorded in provenance exactly as before.

Secrets: this module never logs or stores a key; ``OPENAI_API_KEY`` is
forwarded as a bearer header and nothing more (the Ollama path has no
secret at all).
"""

from __future__ import annotations

import json
import os
import urllib.request
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

#: The local default: small enough to run everywhere, strong at
#: schema-constrained JSON. Override with FLIGHTSIM_LLM_MODEL.
DEFAULT_OLLAMA_MODEL = "qwen2.5:7b"
DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"


def _text_response(text: str, model: str):
    """The anthropic-shaped response compile_prompt_llm reads."""
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason="end_turn",
        model=model,
    )


def _chat_messages(system: Optional[str],
                   messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Anthropic's separate system prompt becomes a leading system turn."""
    chat: List[Dict[str, str]] = []
    if system:
        chat.append({"role": "system", "content": system})
    chat.extend(dict(m) for m in messages)
    return chat


class OllamaClient:
    """A local Ollama server behind the anthropic client interface.

    Uses Ollama's native /api/chat with the ``format`` field, which
    grammar-constrains generation to the compiler's OWN RESPONSE_SCHEMA --
    the same constraint the Claude API applies, enforced locally.
    """

    def __init__(self, host: Optional[str] = None,
                 timeout_s: float = 300.0) -> None:
        self.host = (host or os.environ.get("OLLAMA_HOST")
                     or DEFAULT_OLLAMA_HOST).rstrip("/")
        self.timeout_s = timeout_s
        self.messages = SimpleNamespace(create=self._create)

    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        request = urllib.request.Request(
            self.host + path,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=self.timeout_s) as reply:
            return json.loads(reply.read().decode())

    def _create(self, *, model: str, messages: List[Dict[str, str]],
                system: Optional[str] = None, max_tokens: int = 4096,
                output_config: Optional[Dict[str, Any]] = None,
                **_ignored: Any):
        payload: Dict[str, Any] = {
            "model": model,
            "messages": _chat_messages(system, messages),
            "stream": False,
            # Deterministic-leaning decoding: this is extraction, not prose.
            "options": {"num_predict": int(max_tokens), "temperature": 0.0},
        }
        schema = ((output_config or {}).get("format") or {}).get("schema")
        if schema is not None:
            payload["format"] = schema
        data = self._post("/api/chat", payload)
        text = str((data.get("message") or {}).get("content", ""))
        return _text_response(text, str(data.get("model", model)))


class OpenAICompatClient:
    """Any OpenAI-compatible /chat/completions endpoint, same interface.

    Covers Groq, Gemini's OpenAI compatibility layer, OpenRouter and
    friends. The response_format json_schema field carries the compiler's
    RESPONSE_SCHEMA where the endpoint supports it; endpoints that ignore
    it still face the strict parser.
    """

    def __init__(self, base_url: str, api_key: Optional[str] = None,
                 timeout_s: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key           # forwarded as a header, never logged
        self.timeout_s = timeout_s
        self.messages = SimpleNamespace(create=self._create)

    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        request = urllib.request.Request(
            self.base_url + path, data=json.dumps(payload).encode(),
            headers=headers)
        with urllib.request.urlopen(request, timeout=self.timeout_s) as reply:
            return json.loads(reply.read().decode())

    def _create(self, *, model: str, messages: List[Dict[str, str]],
                system: Optional[str] = None, max_tokens: int = 4096,
                output_config: Optional[Dict[str, Any]] = None,
                **_ignored: Any):
        payload: Dict[str, Any] = {
            "model": model,
            "messages": _chat_messages(system, messages),
            "max_tokens": int(max_tokens),
            "temperature": 0,
        }
        schema = ((output_config or {}).get("format") or {}).get("schema")
        if schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "scenario_fields", "schema": schema,
                                "strict": True},
            }
        data = self._post("/chat/completions", payload)
        choices = data.get("choices") or [{}]
        text = str(((choices[0].get("message")) or {}).get("content", ""))
        return _text_response(text, str(data.get("model", model)))


def resolve_client() -> Optional[Tuple[Any, str]]:
    """(client, default model) for an ALTERNATE provider, or None.

    None means "no alternate provider configured" -- the caller then falls
    through to the Anthropic SDK path (or its named preflight error).
    Selection is by env presence only; misconfiguration (e.g. openai with
    no base URL) raises with the fix named, matching the preflight style.
    """
    provider = os.environ.get("FLIGHTSIM_LLM", "").strip().lower()
    if not provider:
        return None
    if provider == "ollama":
        model = os.environ.get("FLIGHTSIM_LLM_MODEL", DEFAULT_OLLAMA_MODEL)
        return OllamaClient(), model
    if provider == "llm7":
        # The TRUE keyless fail-safe: llm7.io serves OpenAI-compatible chat
        # completions with NO account or key (verified live 2026-08-13; a
        # key via LLM7_API_KEY raises the anonymous rate limits but is
        # optional). Anonymous services can change terms or vanish -- the
        # compiler's strict parsing and loud refusal already cover a dead
        # or degraded endpoint, and the regex parser remains the floor.
        model = os.environ.get("FLIGHTSIM_LLM_MODEL", "gemini-3.1-flash-lite")
        return (OpenAICompatClient(
            "https://api.llm7.io/v1",
            os.environ.get("LLM7_API_KEY") or None), model)
    if provider in ("groq", "openrouter"):
        # The NO-DOWNLOAD fail-safe: free hosted endpoints, OpenAI-compatible.
        # Both need a free account key (no credit card at signup) -- a truly
        # keyless hosted LLM does not legitimately exist, and a shared key in
        # a public repo would be revoked. The key is read from the named env
        # var, never logged, never stored.
        presets = {
            "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY",
                     "llama-3.3-70b-versatile"),
            "openrouter": ("https://openrouter.ai/api/v1",
                           "OPENROUTER_API_KEY",
                           "meta-llama/llama-3.3-70b-instruct:free"),
        }
        base_url, key_var, default_model = presets[provider]
        api_key = os.environ.get(key_var, "").strip()
        if not api_key:
            raise ValueError(
                f"FLIGHTSIM_LLM={provider} needs {key_var} in the server "
                f"process's environment (free account at "
                f"{'console.groq.com' if provider == 'groq' else 'openrouter.ai'})")
        model = os.environ.get("FLIGHTSIM_LLM_MODEL", default_model)
        return OpenAICompatClient(base_url, api_key), model
    if provider == "openai":
        base_url = os.environ.get("OPENAI_BASE_URL", "").strip()
        if not base_url:
            raise ValueError(
                "FLIGHTSIM_LLM=openai needs OPENAI_BASE_URL (and usually "
                "OPENAI_API_KEY) in the server process's environment")
        model = os.environ.get("FLIGHTSIM_LLM_MODEL", "").strip()
        if not model:
            raise ValueError(
                "FLIGHTSIM_LLM=openai needs FLIGHTSIM_LLM_MODEL (the "
                "endpoint's model id) in the server process's environment")
        return (OpenAICompatClient(base_url,
                                   os.environ.get("OPENAI_API_KEY")), model)
    raise ValueError(
        f"unknown FLIGHTSIM_LLM provider {provider!r}; supported: "
        f"'llm7' (hosted, keyless), 'ollama' (local, free), 'groq' / "
        f"'openrouter' (hosted, free tier, key needed), 'openai' (any "
        f"OpenAI-compatible endpoint)")
