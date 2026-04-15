import httpx


async def send_webhook(url: str, payload: dict) -> None:
    """Best-effort webhook delivery — failures are silently ignored."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(url, json=payload)
    except Exception:
        pass
