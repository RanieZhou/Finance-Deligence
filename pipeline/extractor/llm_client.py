"""
DeepSeek API 客户端封装（OpenAI 兼容接口）
"""
from __future__ import annotations
import json
import os
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI
from loguru import logger

load_dotenv()

_client: OpenAI | None = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        )
    return _client


def extract_json(
    system_prompt: str,
    user_prompt: str,
    model: str | None = None,
    temperature: float = 0.1,
    max_retries: int = 2,
) -> dict | list:
    """
    调用 LLM，要求返回 JSON，带重试。
    temperature=0.1 确保输出稳定。
    """
    model = model or os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    client = get_client()

    for attempt in range(max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                temperature=temperature,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            content = response.choices[0].message.content
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.warning(f"JSON decode error (attempt {attempt+1}): {e}")
            if attempt == max_retries:
                raise
        except Exception as e:
            logger.error(f"LLM call failed (attempt {attempt+1}): {e}")
            if attempt == max_retries:
                raise

    return {}
