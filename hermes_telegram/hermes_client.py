import httpx
import os


class HermesClient:
    def __init__(self):
        self.host = os.environ["OLLAMA_HOST"].rstrip("/")
        self.model = os.environ["HERMES_MODEL"]
        self.system_prompt = os.environ.get("SYSTEM_PROMPT", "You are a helpful assistant.")

    async def chat(self, message: str, history: list[dict] | None = None) -> str:
        messages = [{"role": "system", "content": self.system_prompt}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": message})

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{self.host}/api/chat",
                json={"model": self.model, "messages": messages, "stream": False},
            )
            resp.raise_for_status()
            data = resp.json()
            return data["message"]["content"]

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.host}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False
