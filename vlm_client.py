"""
vlm_client.py
=============
VLM interface with Groq (Llama 4 Scout) as primary backend.

Handles:
- Base64 image encoding for the API
- Strict JSON-only response parsing
- Retry on malformed responses (strips markdown fences, re-parses)
- Clear error messages for the GUI log

Requires:
    pip install groq Pillow

Set your API key:
    export GROQ_API_KEY="gsk_..."
or pass it directly to VlmClient(api_key="gsk_...").
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
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

from system_prompt import SYSTEM_PROMPT


class VlmClient:
    """
    Sends a user turn (image + JSON state) to the VLM and returns the
    parsed response dict.
    """

    MODEL   = "meta-llama/llama-4-scout-17b-16e-instruct"
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

    # ------------------------------------------------------------------
    # Primary method
    # ------------------------------------------------------------------

    def call(self, turn_parts: list[dict]) -> tuple[dict, str]:
        """
        Send a user turn to the VLM and return the parsed response.

        Args:
            turn_parts: List of content parts from UserTurnBuilder.build().
                        Each part is either {"inline_data": ...} or {"text": ...}.

        Returns:
            Tuple of (parsed_response_dict, raw_text).
            On failure after all retries, returns ({}, error_message).
        """
        # Convert UserTurnBuilder parts → Groq message format
        content = self._convert_parts(turn_parts)

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": content},
        ]

        last_error = ""
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                raw = self._api_call(messages)
                parsed = self._parse_json(raw)
                if parsed is not None:
                    return parsed, raw

                last_error = f"Attempt {attempt}: JSON parse failed.\nRaw: {raw[:300]}"
                print(f"[VLM] {last_error}")

                # Add the bad response + correction request to messages and retry
                messages.append({"role": "assistant", "content": raw})
                messages.append({
                    "role": "user",
                    "content": (
                        "Your response was not valid JSON. "
                        "Reply with the JSON block only — "
                        "no markdown, no backticks, no explanation."
                    )
                })

            except Exception as e:
                last_error = f"Attempt {attempt}: API error — {e}"
                print(f"[VLM] {last_error}")

        return {}, f"[VLM] Failed after {self.MAX_RETRIES} attempts. Last error: {last_error}"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _api_call(self, messages: list[dict]) -> str:
        response = self._client.chat.completions.create(
            model      =self.MODEL,
            messages   =messages,
            max_tokens =self.MAX_TOKENS,
            temperature=0.2,   # low temperature for consistent structured output
        )
        return response.choices[0].message.content or ""

    @staticmethod
    def _parse_json(text: str) -> Optional[dict]:
        """
        Try to extract a JSON object from the model response.
        Handles markdown fences and leading/trailing whitespace.
        """
        # Strip markdown code fences if present
        clean = re.sub(r"```(?:json)?", "", text).strip()

        # Try direct parse first
        try:
            return json.loads(clean)
        except json.JSONDecodeError:
            pass

        # Try to find the first {...} block in the text
        match = re.search(r"\{.*\}", clean, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        return None

    @staticmethod
    def _convert_parts(parts: list[dict]) -> list[dict]:
        """
        Convert UserTurnBuilder parts to Groq/OpenAI message content format.

        UserTurnBuilder produces:
            {"inline_data": {"mime_type": "image/png", "data": "<base64>"}}
            {"text": "..."}

        Groq expects:
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
            {"type": "text",      "text": "..."}
        """
        converted = []
        for part in parts:
            if "inline_data" in part:
                mime = part["inline_data"]["mime_type"]
                data = part["inline_data"]["data"]
                converted.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime};base64,{data}"
                    }
                })
            elif "text" in part:
                converted.append({
                    "type": "text",
                    "text": part["text"]
                })
        return converted
