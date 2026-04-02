"""
vlm_client.py
=============
VLM backends: Groq (Llama 4 Scout) and Google Gemini.

Usage:
    client = create_vlm_client("groq")    # default
    client = create_vlm_client("gemini")  # needs GEMINI_API_KEY

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
    MAX_TOKENS  = 2048
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
                # finish_reason 2 = SAFETY, 3 = RECITATION, etc.
                if response.candidates:
                    finish_reason = response.candidates[0].finish_reason
                    if finish_reason not in (0, 1):  # 0=UNSPECIFIED, 1=STOP
                        last_error = (
                            f"Attempt {attempt}: Gemini blocked response "
                            f"(finish_reason={finish_reason}). "
                            "Try rephrasing the system prompt or image."
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
# Factory
# ----------------------------------------------------------------------

def create_vlm_client(backend: str = "groq") -> "VlmClient | GeminiVlmClient":
    """
    Instantiate the right VLM client.

    Args:
        backend: "groq" (default) or "gemini"
    """
    if backend == "gemini":
        return GeminiVlmClient()
    return VlmClient()
