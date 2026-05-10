import json
from openai import OpenAI
from src.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

_client = None


def _get_client():
    global _client
    if _client is None and DEEPSEEK_API_KEY:
        _client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
    return _client


def has_api_key() -> bool:
    return bool(DEEPSEEK_API_KEY)


def chat(messages: list[dict], temperature: float = 0.3, max_tokens: int = 2048) -> str:
    """Call DeepSeek chat. Returns response text or empty string on failure."""
    client = _get_client()
    if client is None:
        return ""
    try:
        resp = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content or ""
    except Exception:
        return ""


def chat_json(messages: list[dict], temperature: float = 0.2, max_tokens: int = 2048) -> dict | list | None:
    """Call DeepSeek and parse JSON response."""
    text = chat(messages, temperature, max_tokens)
    if not text:
        return None
    try:
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("\n```", 1)[0]
        return json.loads(text)
    except json.JSONDecodeError:
        return None
