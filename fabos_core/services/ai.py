"""Provider-neutral FabOS AI assistant with safe, read-only business tools.

The AI may inspect bounded business context and draft content. It cannot mutate
business data, publish externally, spend money, or perform consequential actions.
Secrets are referenced through environment variables and are never persisted here.
"""
import json
import os
import urllib.error
import urllib.request
import uuid


class AIService:
    PROVIDERS = ("disabled", "openai_compatible", "ollama")
    MAX_TOOL_ROUNDS = 3

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
            "tools": [item["name"] for item in self.tool_definitions()],
            "action_approval_required": self._setting("ai_require_action_approval", "true").lower() in ("1", "true", "yes", "on"),
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
            "FabOS confirms it. Do not invent product, order, inventory, customer, pricing, license, "
            "or production facts. You have only the read-only tools explicitly supplied to you. "
            "External marketing is draft/recommendation only. Never publish, change prices, issue refunds, "
            "send customer messages, create production jobs, delete records, or spend money from AI chat. "
            "If asked to perform a consequential action, explain that owner confirmation and a dedicated "
            "FabOS action workflow are required."
        )

    def tool_definitions(self):
        return [
            {
                "type": "function",
                "function": {
                    "name": "search_products",
                    "description": "Search the FabOS product catalog. Read-only.",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 20}},
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_product",
                    "description": "Get one product and its image metadata. Read-only.",
                    "parameters": {
                        "type": "object",
                        "properties": {"product_id": {"type": "string"}},
                        "required": ["product_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "business_snapshot",
                    "description": "Get bounded operational counts for orders, production, printers, inventory and quotes. Read-only.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "order_summary",
                    "description": "Get a bounded list of recent orders. Customer-sensitive fields are omitted unless explicitly enabled in AI settings.",
                    "parameters": {
                        "type": "object",
                        "properties": {"status": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 20}},
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "marketing_snapshot",
                    "description": "Get marketing channels, post counts and recent marketplace sales totals. Read-only.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
        ]

    def _tool_result(self, name, args):
        args = args or {}
        if name == "search_products":
            query = str(args.get("query", "")).strip()
            limit = min(max(int(args.get("limit", 10) or 10), 1), 20)
            rows = self.products.list(query=query) if self.products else []
            return {"products": [dict(row) for row in rows[:limit]]}
        if name == "get_product":
            product_id = str(args.get("product_id", "")).strip()
            product = self.products.get(product_id) if self.products else None
            if not product:
                return {"error": "Product not found"}
            images = self.products.images(product_id) if self.products else []
            return {"product": dict(product), "images": [dict(row) for row in images[:10]]}
        if name == "business_snapshot":
            with self.database.connect() as conn:
                def scalar(sql, args=()):
                    return int(conn.execute(sql, args).fetchone()[0] or 0)
                threshold = float(self._setting("filament_low_threshold_g", "250") or 250)
                return {
                    "orders_today": scalar("SELECT COUNT(*) FROM orders WHERE date(created_at)=date('now') AND status<>'cancelled'"),
                    "active_orders": scalar("SELECT COUNT(*) FROM orders WHERE status NOT IN ('completed','cancelled','shipped')"),
                    "open_quotes": scalar("SELECT COUNT(*) FROM quotes WHERE status IN ('draft','sent')"),
                    "active_print_jobs": scalar("SELECT COUNT(*) FROM print_jobs WHERE status IN ('queued','scheduled','printing','paused')"),
                    "printing_jobs": scalar("SELECT COUNT(*) FROM print_jobs WHERE status IN ('printing','paused')"),
                    "failed_print_jobs": scalar("SELECT COUNT(*) FROM print_jobs WHERE status='failed'"),
                    "printers": scalar("SELECT COUNT(*) FROM printers"),
                    "low_filament_spools": scalar("SELECT COUNT(*) FROM filament_spools WHERE active=1 AND remaining_g<?", (threshold,)),
                }
        if name == "order_summary":
            status = str(args.get("status", "")).strip().lower()
            limit = min(max(int(args.get("limit", 10) or 10), 1), 20)
            allowed = {"pending", "confirmed", "in_production", "qc", "ready", "shipped", "completed", "cancelled"}
            where, params = [], []
            if status in allowed:
                where.append("o.status=?")
                params.append(status)
            sql = (
                "SELECT o.id,o.order_number,o.status,o.total_cents,o.due_at,o.created_at,"
                "COALESCE(q.quote_number,'') quote_number FROM orders o "
                "LEFT JOIN quotes q ON q.id=o.quote_id"
            )
            if where:
                sql += " WHERE " + " AND ".join(where)
            sql += " ORDER BY o.created_at DESC LIMIT ?"
            params.append(limit)
            with self.database.connect() as conn:
                rows = [dict(row) for row in conn.execute(sql, params).fetchall()]
            return {"orders": rows}
        if name == "marketing_snapshot":
            if not self.marketing:
                return {"error": "Marketing service unavailable"}
            return self.marketing.dashboard()
        raise ValueError("Unsupported AI tool")

    def _request(self, messages, use_tools=True):
        provider = self._setting("ai_provider", "disabled")
        model = self._setting("ai_model", "")
        endpoint = self._setting("ai_endpoint", "")
        if provider == "ollama":
            endpoint = endpoint.rstrip("/") + "/api/chat"
            payload = {"model": model, "messages": messages, "stream": False}
            if use_tools:
                payload["tools"] = self.tool_definitions()
        elif provider == "openai_compatible":
            endpoint = endpoint.rstrip("/") + "/chat/completions"
            payload = {"model": model, "messages": messages, "temperature": 0.3}
            if use_tools:
                payload["tools"] = self.tool_definitions()
                payload["tool_choice"] = "auto"
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

        message = result.get("message", {}) if provider == "ollama" else result.get("choices", [{}])[0].get("message", {})
        return message, result

    def _conversation(self, conversation_id=None, user_id=None):
        if not self.database:
            return conversation_id or str(uuid.uuid4())
        conversation_id = conversation_id or str(uuid.uuid4())
        try:
            with self.database.connect() as conn:
                exists = conn.execute("SELECT id FROM ai_conversations WHERE id=?", (conversation_id,)).fetchone()
                if not exists:
                    conn.execute("INSERT INTO ai_conversations(id,user_id) VALUES(?,?)", (conversation_id, user_id))
                    conn.commit()
        except Exception:
            pass
        return conversation_id

    def _record_message(self, conversation_id, role, content):
        if not self.database:
            return
        with self.database.connect() as conn:
            conn.execute("INSERT INTO ai_messages(id,conversation_id,role,content) VALUES(?,?,?,?)",
                         (str(uuid.uuid4()), conversation_id, role, str(content or "")[:20000]))
            conn.execute("UPDATE ai_conversations SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (conversation_id,))
            conn.commit()

    def _record_tool_event(self, conversation_id, user_id, name, arguments, result):
        if not self.database:
            return
        with self.database.connect() as conn:
            conn.execute("INSERT INTO ai_tool_events(id,conversation_id,user_id,tool_name,arguments_json,result_json) VALUES(?,?,?,?,?,?)",
                         (str(uuid.uuid4()), conversation_id, user_id, name,
                          json.dumps(arguments, default=str)[:12000], json.dumps(result, default=str)[:16000]))
            conn.commit()

    def chat(self, message, context=None, conversation_id=None, user_id=None):
        if not message or not str(message).strip():
            raise ValueError("Message is required")
        conversation_id = self._conversation(conversation_id, user_id)\n        messages = [{"role": "system", "content": self._system_prompt()}]
        if context:
            safe_context = dict(context)
            if not self._setting("ai_allow_customer_data", "false").lower() in ("1", "true", "yes", "on"):
                safe_context.pop("customer", None)
                safe_context.pop("customers", None)
            messages.append({"role": "system", "content": "FabOS context:\n" + json.dumps(safe_context, default=str)[:12000]})
        user_message = str(message).strip()[:12000]\n        messages.append({"role": "user", "content": user_message})\n        self._record_message(conversation_id, "user", user_message)

        for _ in range(self.MAX_TOOL_ROUNDS):
            response_message, _ = self._request(messages, use_tools=True)
            tool_calls = response_message.get("tool_calls") or []
            if not tool_calls:
                answer = response_message.get("content", "") or ""\n                self._record_message(conversation_id, "assistant", answer)\n                return {"conversation_id": conversation_id, "response": answer}
            assistant_message = {
                "role": "assistant",
                "content": response_message.get("content") or "",
                "tool_calls": tool_calls,
            }
            messages.append(assistant_message)
            for call in tool_calls:
                function = call.get("function", {})
                name = function.get("name", "")
                try:
                    arguments = json.loads(function.get("arguments") or "{}")
                    output = self._tool_result(name, arguments)\n                    self._record_tool_event(conversation_id, user_id, name, arguments, output)
                except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
                    output = {"error": str(exc)}
                tool_message = {
                    "role": "tool",
                    "tool_call_id": call.get("id", ""),
                    "name": name,
                    "content": json.dumps(output, default=str)[:16000],
                }
                messages.append(tool_message)
        raise RuntimeError("AI exceeded the safe tool-call limit")

    def product_assistant(self, product_id, instruction="Create useful marketing copy for this product."):
        product = self.products.get(product_id)
        if not product:
            raise ValueError("Product not found")
        context = {"product": dict(product)}
        images = self.products.images(product_id)
        if images:
            context["images"] = [dict(row) for row in images]
        result = self.chat(instruction, context)\n        return result["response"] if isinstance(result, dict) else result

    def marketing_assistant(self, product_id):
        return self.product_assistant(
            product_id,
            "Create a complete draft marketing package for this product: website description, Etsy/eBay listing draft, "
            "Facebook/Instagram/TikTok/Pinterest captions, 5-10 relevant hashtags, and a clear call to action. "
            "Do not invent materials, dimensions, certifications, licensing rights, shipping times, or capabilities.",
        )
