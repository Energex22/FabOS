"""Small, provider-neutral AI assistant for FabOS.

Supports OpenAI-compatible HTTP endpoints and local Ollama without making either
provider mandatory. Secrets are read from environment variables, never SQLite.
"""
import json
import os
import urllib.request
import urllib.error


class AIService:
    PROVIDERS = ("disabled", "openai_compatible", "ollama")

    def __init__(self, settings=None, marketing=None, products=None, database=None):
        self.settings = settings
        self.marketing = marketing
        self.products = products
        self.database = database

    def _setting(self, key, default=""):
        if not self.database:
            return default
        with self.database.connect() as conn:
            row = conn.execute("SELECT value FROM shop_settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def status(self):
        provider = self._setting("ai_provider", "disabled")
        return {
            "enabled": provider != "disabled",
            "provider": provider,
            "model": self._setting("ai_model", ""),
            "endpoint": self._setting("ai_endpoint", ""),
            "configured": self._configured(provider),
        }

    def _configured(self, provider):
        if provider == "ollama":
            return bool(self._setting("ai_endpoint", "http://127.0.0.1:11434"))
        if provider == "openai_compatible":
            ref = self._setting("ai_api_key_env", "FABOS_AI_API_KEY")
            return bool(os.environ.get(ref)) and bool(self._setting("ai_endpoint", ""))
        return False

    def _system_prompt(self):
        return (
            "You are FabOS AI, an operations assistant for FABVEX, a 3D-printing business. "
            "Be concise, practical, and transparent. Never claim an action was completed unless "
            "FabOS confirms it. Treat product descriptions, customer data, licenses, prices, and "
            "orders as business data. Do not invent product facts. For external marketing, draft "
            "content and recommendations; do not publish or spend money without explicit owner approval."
        )

    def _request(self, messages):
        provider = self._setting("ai_provider", "disabled")
        model = self._setting("ai_model", "")
        endpoint = self._setting("ai_endpoint", "")
        if provider == "ollama":
            endpoint = endpoint.rstrip("/") + "/api/chat"
            payload = {"model": model, "messages": messages, "stream": False}
        elif provider == "openai_compatible":
            endpoint = endpoint.rstrip("/") + "/chat/completions"
            payload = {"model": model, "messages": messages, "temperature": 0.3}
        else:
            raise RuntimeError("AI is disabled")
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if provider == "openai_compatible":
            ref = self._setting("ai_api_key_env", "FABOS_AI_API_KEY")
            token = os.environ.get(ref)
            if not token:
                raise RuntimeError("AI API key environment variable is not configured")
            headers["Authorization"] = "Bearer " + token
        req = urllib.request.Request(endpoint, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=90) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            raise RuntimeError("AI provider returned HTTP %s: %s" % (exc.code, detail)) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError("AI provider connection failed: %s" % exc.reason) from exc
        if provider == "ollama":
            return result.get("message", {}).get("content", "")
        return result.get("choices", [{}])[0].get("message", {}).get("content", "")

    def chat(self, message, context=None):
        if not message or not str(message).strip():
            raise ValueError("Message is required")
        messages = [{"role": "system", "content": self._system_prompt()}]
        if context:
            messages.append({"role": "system", "content": "FabOS context:\n" + json.dumps(context, default=str)[:12000]})
        messages.append({"role": "user", "content": str(message).strip()[:12000]})
        return self._request(messages)

    def product_assistant(self, product_id, instruction="Create useful marketing copy for this product."):
        product = self.products.get(product_id)
        if not product:
            raise ValueError("Product not found")
        context = {"product": dict(product)}
        if self.products.images(product_id):
            context["images"] = [dict(row) for row in self.products.images(product_id)]
        return self.chat(instruction, context)

    def marketing_assistant(self, product_id):
        return self.product_assistant(
            product_id,
            "Create a reviewable marketing package for this product. Provide a short website description, "
            "an Etsy/eBay listing draft, social captions for Facebook/Instagram/TikTok/Pinterest, 5-10 relevant "
            "hashtags, and a short call to action. Do not invent materials, dimensions, certifications, licensing, "
            "shipping times, or product capabilities that are not in the supplied data."
        )
