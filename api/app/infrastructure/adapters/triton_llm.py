import re

import httpx

from app.domain.ports.llm import LLMPort


class TritonLLMAdapter(LLMPort):
    """LLM adapter — calls qwen35_llm via vLLM /generate endpoint on Triton."""

    def __init__(self, triton_url: str, system_prompt: str, max_tokens: int = 500) -> None:
        self._generate_url = f"http://{triton_url}/v2/models/qwen35_llm/generate"
        self._system_prompt = system_prompt
        self._max_tokens = max_tokens
        self._client = httpx.AsyncClient(timeout=60.0)

    def _build_prompt(self, user_message: str) -> str:
        return (
            f"<|im_start|>system\n{self._system_prompt}<|im_end|>\n"
            f"<|im_start|>user\n{user_message} /no_think<|im_end|>\n"
            f"<|im_start|>assistant\n"
        )

    def _extract_response(self, text_output: str) -> str:
        text = text_output.split("<|im_start|>assistant\n")[-1]
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        return text.strip()

    async def generate(self, message: str) -> str:
        resp = await self._client.post(
            self._generate_url,
            json={
                "text_input": self._build_prompt(message),
                "max_tokens": self._max_tokens,
                "stream": False,
                "stop": "<|im_end|>",
            },
        )
        resp.raise_for_status()
        return self._extract_response(resp.json()["text_output"])

    async def aclose(self) -> None:
        await self._client.aclose()
