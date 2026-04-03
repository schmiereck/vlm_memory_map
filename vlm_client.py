"""
vlm_client.py
=============
VLM backends: Groq (Llama 4 Scout), Google Gemini, and local Ollama.

Usage:
    client = create_vlm_client("groq")              # default
    client = create_vlm_client("gemini")             # needs GEMINI_API_KEY
    client = create_vlm_client("ollama")             # local Ollama, default model
    client = create_vlm_client("ollama", model="gemma3:4b")

Both expose the same interface:
    response_dict, raw_text = client.call(turn_parts)
"""

import os
import json
import base64
import re
from io import BytesIO
from typing import Optional

try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False

try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

from system_prompt import SYSTEM_PROMPT


# ----------------------------------------------------------------------
# Shared helpers
# ----------------------------------------------------------------------

def _parse_json(text: str) -> Optional[dict]:
    """Extract a JSON object from model output (strips markdown fences etc.)."""
    clean = re.sub(r"```(?:json)?", "", text).strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", clean, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None


# ----------------------------------------------------------------------
# Groq backend  (Llama 4 Scout)
# ----------------------------------------------------------------------

class VlmClient:
    """Groq / Llama backend — default."""

    MODEL      = "meta-llama/llama-4-scout-17b-16e-instruct"
    MAX_TOKENS = 2048
    MAX_RETRIES = 3

    def __init__(self, api_key: Optional[str] = None):
        key = api_key or os.environ.get("GROQ_API_KEY", "")
        if not key:
            raise ValueError(
                "No Groq API key found. "
                "Set GROQ_API_KEY environment variable or pass api_key=..."
            )
        if not GROQ_AVAILABLE:
            raise ImportError("groq package not installed. Run: pip install groq")
        self._client = Groq(api_key=key)

    def call(self, turn_parts: list[dict]) -> tuple[dict, str]:
        content  = self._convert_parts(turn_parts)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": content},
        ]
        last_error = ""
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                raw    = self._api_call(messages)
                parsed = _parse_json(raw)
                if parsed is not None:
                    return parsed, raw
                last_error = f"Attempt {attempt}: JSON parse failed.\nRaw: {raw[:300]}"
                print(f"[VLM] {last_error}")
                messages.append({"role": "assistant", "content": raw})
                messages.append({
                    "role": "user",
                    "content": (
                        "Your response was not valid JSON. "
                        "Reply with the JSON block only — "
                        "no markdown, no backticks, no explanation."
                    ),
                })
            except Exception as e:
                last_error = f"Attempt {attempt}: API error — {e}"
                print(f"[VLM] {last_error}")
        return {}, f"[VLM] Failed after {self.MAX_RETRIES} attempts. Last error: {last_error}"

    def _api_call(self, messages: list[dict]) -> str:
        response = self._client.chat.completions.create(
            model      =self.MODEL,
            messages   =messages,
            max_tokens =self.MAX_TOKENS,
            temperature=0.2,
        )
        return response.choices[0].message.content or ""

    @staticmethod
    def _convert_parts(parts: list[dict]) -> list[dict]:
        """Convert UserTurnBuilder parts → Groq/OpenAI content format."""
        converted = []
        for part in parts:
            if "inline_data" in part:
                mime = part["inline_data"]["mime_type"]
                data = part["inline_data"]["data"]
                converted.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{data}"},
                })
            elif "text" in part:
                converted.append({"type": "text", "text": part["text"]})
        return converted


# ----------------------------------------------------------------------
# Gemini backend
# ----------------------------------------------------------------------

class GeminiVlmClient:
    """Google Gemini backend."""

    MODEL       = "models/gemini-robotics-er-1.5-preview"
    MAX_TOKENS  = 8192
    MAX_RETRIES = 3

    def __init__(self, api_key: Optional[str] = None):
        key = api_key or os.environ.get("GEMINI_API_KEY", "")
        if not key:
            raise ValueError(
                "No Gemini API key found. "
                "Set GEMINI_API_KEY environment variable or pass api_key=..."
            )
        if not GEMINI_AVAILABLE:
            raise ImportError(
                "google-generativeai not installed. "
                "Run: pip install google-generativeai"
            )
        genai.configure(api_key=key)
        self._model = genai.GenerativeModel(
            model_name=self.MODEL,
            system_instruction=SYSTEM_PROMPT,
            generation_config=genai.types.GenerationConfig(
                temperature=0.2,
                max_output_tokens=self.MAX_TOKENS,
            ),
        )

    def call(self, turn_parts: list[dict]) -> tuple[dict, str]:
        content    = self._convert_parts(turn_parts)
        last_error = ""
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                response = self._model.generate_content(content)

                # Check finish_reason before accessing .text
                # Gemini FinishReason: 1=STOP, 2=MAX_TOKENS, 3=SAFETY, 4=RECITATION
                if response.candidates:
                    finish_reason = response.candidates[0].finish_reason
                    if finish_reason == 2:  # MAX_TOKENS — response truncated
                        last_error = (
                            f"Attempt {attempt}: Gemini hit token limit "
                            f"(finish_reason=MAX_TOKENS). Response was truncated."
                        )
                        print(f"[VLM] {last_error}")
                        continue
                    elif finish_reason not in (0, 1):  # SAFETY, RECITATION, OTHER
                        last_error = (
                            f"Attempt {attempt}: Gemini blocked response "
                            f"(finish_reason={finish_reason})."
                        )
                        print(f"[VLM] {last_error}")
                        continue

                raw    = response.text
                parsed = _parse_json(raw)
                if parsed is not None:
                    return parsed, raw
                last_error = f"Attempt {attempt}: JSON parse failed.\nRaw: {raw[:300]}"
                print(f"[VLM] {last_error}")
            except Exception as e:
                last_error = f"Attempt {attempt}: API error — {e}"
                print(f"[VLM] {last_error}")
        return {}, f"[VLM] Failed after {self.MAX_RETRIES} attempts. Last error: {last_error}"

    @staticmethod
    def _convert_parts(parts: list[dict]) -> list:
        """Convert UserTurnBuilder parts → Gemini content parts."""
        converted = []
        for part in parts:
            if "inline_data" in part:
                mime = part["inline_data"]["mime_type"]
                data = base64.b64decode(part["inline_data"]["data"])
                converted.append({"mime_type": mime, "data": data})
            elif "text" in part:
                converted.append(part["text"])
        return converted


# ----------------------------------------------------------------------
# Ollama backend  (local)
# ----------------------------------------------------------------------

class OllamaVlmClient:
    """Local Ollama backend — no API key required.

    Requires Ollama running at localhost:11434.
    Vision-capable models tested:
      gemma3n:e2b  — Gemma 3n Effective-2B, 5.6 GB  (recommended)
      gemma3n:e4b  — Gemma 3n Effective-4B, 9.8 GB
      gemma3:4b    — Gemma 3 4B, 3.3 GB

    Install:  https://ollama.com
    Pull:     ollama pull gemma3n:e2b
    """

    BASE_URL      = "http://localhost:11434"
    DEFAULT_MODEL = "gemma3n:e2b"
    MAX_TOKENS    = 16384   # thinking models need extra budget for reasoning tokens
    MAX_RETRIES   = 3

    def __init__(self, model: str = DEFAULT_MODEL):
        try:
            import requests as _req
            self._requests = _req
        except ImportError:
            raise ImportError("requests not installed. Run: pip install requests")
        self._model = model
        self.MODEL  = model   # expose as attribute for logging (matches other clients)

    def call(self, turn_parts: list[dict]) -> tuple[dict, str]:
        # Split parts into images (base64) and text
        images: list[str] = []
        texts:  list[str] = []
        for part in turn_parts:
            if "inline_data" in part:
                images.append(part["inline_data"]["data"])
            elif "text" in part:
                texts.append(part["text"])

        message: dict = {
            "role":    "user",
            "content": "\n\n".join(texts),
        }
        if images:
            message["images"] = images

        payload = {
            "model":  self._model,
            "stream": False,
            "options": {"num_predict": self.MAX_TOKENS, "temperature": 0.2},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                message,
            ],
        }

        last_error = ""
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                resp = self._requests.post(
                    f"{self.BASE_URL}/api/chat",
                    json=payload,
                    timeout=600,
                )
                if not resp.ok:
                    raise RuntimeError(
                        f"HTTP {resp.status_code}: {resp.text.strip()[:200]}"
                    )
                data = resp.json()
                msg  = data.get("message", {})
                raw  = msg.get("content", "").strip()

                # Thinking models (e.g. gemma4) put reasoning in "thinking" and
                # the actual reply in "content". If content is empty but thinking
                # is not, the model ran out of tokens mid-think — log and retry.
                if not raw:
                    thinking    = msg.get("thinking", "")
                    done_reason = data.get("done_reason", "unknown")
                    if thinking and done_reason == "length":
                        last_error = (
                            f"Attempt {attempt}: thinking model ran out of tokens "
                            f"before producing output (done_reason=length). "
                            f"Thinking excerpt: {thinking[:150]!r}"
                        )
                    else:
                        last_error = (
                            f"Attempt {attempt}: empty response "
                            f"(done_reason={done_reason})."
                        )
                    print(f"[VLM] {last_error}")
                    # On retry, strip images to reduce context pressure
                    if attempt == 1 and images:
                        print("[VLM] Retrying without image to reduce context size...")
                        payload["messages"][-1] = {
                            "role":    "user",
                            "content": message["content"] + "\n[Image omitted on retry]",
                        }
                    continue

                parsed = _parse_json(raw)
                if parsed is not None:
                    return parsed, raw

                # JSON parse failed — append correction and retry (like Groq backend)
                last_error = f"Attempt {attempt}: JSON parse failed.\nRaw: {raw[:300]}"
                print(f"[VLM] {last_error}")
                payload["messages"].append({"role": "assistant", "content": raw})
                payload["messages"].append({
                    "role":    "user",
                    "content": (
                        "Your previous response was not valid JSON. "
                        "Output the JSON object only — no prose, no markdown, "
                        "no backticks, no explanation. Start with { and end with }."
                    ),
                })
            except Exception as e:
                last_error = f"Attempt {attempt}: API error — {e}"
                print(f"[VLM] {last_error}")
        return {}, f"[VLM] Failed after {self.MAX_RETRIES} attempts. Last error: {last_error}"


# ----------------------------------------------------------------------
# Factory
# ----------------------------------------------------------------------

def create_vlm_client(backend: str = "groq", model: str = "") -> object:
    """
    Instantiate the right VLM client.

    Args:
        backend: "groq" (default), "gemini", or "ollama"
        model:   Optional model override (only used by ollama backend).
    """
    if backend == "gemini":
        return GeminiVlmClient()
    if backend == "ollama":
        m = model or OllamaVlmClient.DEFAULT_MODEL
        return OllamaVlmClient(model=m)
    return VlmClient()
