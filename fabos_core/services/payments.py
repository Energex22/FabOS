"""Provider-neutral payment orchestration for FabOS.

FabOS owns the order/payment record while gateway adapters own provider-specific
HTTP calls and webhook verification. Card data is never stored in FabOS.
"""
import base64
import hashlib
import hmac
import json
import os
import time
import urllib.parse
import urllib.request
import uuid


class PaymentProviderNotConfigured(RuntimeError):
    pass


class PaymentProviderError(RuntimeError):
    pass


class PaymentProvider:
    name = "base"
    def create_checkout(self, *, payment_id, amount_cents, currency, metadata): raise NotImplementedError
    def create_physical_payment(self, *, payment_id, amount_cents, currency, source_id, metadata): raise PaymentProviderNotConfigured("Physical payment is not supported by this provider")
    def parse_webhook(self, payload, signature=None): raise NotImplementedError


class UnconfiguredPaymentProvider(PaymentProvider):
    name = "unconfigured"
    def create_checkout(self, **kwargs): raise PaymentProviderNotConfigured("No payment provider is configured")
    def parse_webhook(self, payload, signature=None): raise PaymentProviderNotConfigured("No payment provider is configured")


class StripePaymentProvider(PaymentProvider):
    name = "stripe"
    api_base = "https://api.stripe.com/v1"
    def __init__(self):
        self.secret_key = os.environ.get("STRIPE_SECRET_KEY", "").strip()
        self.webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()
        if not self.secret_key: raise PaymentProviderNotConfigured("STRIPE_SECRET_KEY is not configured")
    def _request(self, path, fields, idempotency_key=None):
        body = urllib.parse.urlencode(fields).encode("utf-8")
        headers={"Authorization":"Bearer "+self.secret_key,"Content-Type":"application/x-www-form-urlencoded","User-Agent":"FabOS/1.0"}
        if idempotency_key: headers["Idempotency-Key"]=str(idempotency_key)
        request = urllib.request.Request(self.api_base + path, data=body, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=15) as response: return json.loads(response.read().decode("utf-8"))
        except Exception as exc: raise PaymentProviderError("Stripe request failed") from exc
    def create_checkout(self, *, payment_id, amount_cents, currency, metadata):
        success_url=os.environ.get("STRIPE_SUCCESS_URL","").strip();cancel_url=os.environ.get("STRIPE_CANCEL_URL","").strip()
        if not success_url or not cancel_url: raise PaymentProviderNotConfigured("STRIPE_SUCCESS_URL and STRIPE_CANCEL_URL are required")
        fields={"mode":"payment","success_url":success_url,"cancel_url":cancel_url,"line_items[0][price_data][currency]":currency.lower(),"line_items[0][price_data][product_data][name]":"FabOS order "+str(metadata["order_id"]),"line_items[0][price_data][unit_amount]":str(int(amount_cents)),"line_items[0][quantity]":"1","client_reference_id":str(metadata["order_id"]),"metadata[payment_id]":str(payment_id),"metadata[order_id]":str(metadata["order_id"])}
        session=self._request("/checkout/sessions",fields,idempotency_key=payment_id)
        return {"provider_payment_id":session.get("payment_intent") or session.get("id"),"checkout_url":session.get("url"),"status":"pending","metadata":{**metadata,"stripe_session_id":session.get("id")}}
    def parse_webhook(self,payload,signature=None):
        if not self.webhook_secret: raise PaymentProviderNotConfigured("STRIPE_WEBHOOK_SECRET is not configured")
        if not signature: raise PaymentProviderError("Missing Stripe webhook signature")
        _verify_stripe_signature(payload,signature,self.webhook_secret)
        event=json.loads(payload.decode("utf-8") if isinstance(payload,bytes) else payload);event_type=str(event.get("type") or "");obj=((event.get("data") or {}).get("object") or {});metadata=obj.get("metadata") or {};status=None;amount_cents=None
        if event_type == "checkout.session.completed":
            # Checkout completion is not always the same as funds being settled;
            # async payment methods can complete the session while payment is still processing.
            status = "paid" if str(obj.get("payment_status") or "").lower() == "paid" else "pending"
            amount_cents = int(obj.get("amount_total") or 0)
        elif event_type in {"checkout.session.async_payment_succeeded","payment_intent.succeeded","charge.succeeded"}:
            status="paid"
            amount_cents = int(obj.get("amount_received") or obj.get("amount") or 0)
        elif event_type in {"checkout.session.async_payment_failed","payment_intent.payment_failed","charge.failed"}: status="failed"
        elif event_type=="checkout.session.expired": status="cancelled"
        elif event_type in {"charge.refunded","refund.created"}: status="refunded"
        return {"event_id":str(event.get("id") or ""),"event_type":event_type,"provider_payment_id":str(obj.get("payment_intent") or obj.get("id") or ""),"payment_id":str(metadata.get("payment_id") or ""),"order_id":str(metadata.get("order_id") or obj.get("client_reference_id") or ""),"status":status,"amount_cents":amount_cents}


class SquarePaymentProvider(PaymentProvider):
    name="square"
    api_base="https://connect.squareup.com/v2"
    def __init__(self):
        self.access_token=os.environ.get("SQUARE_ACCESS_TOKEN","").strip();self.location_id=os.environ.get("SQUARE_LOCATION_ID","").strip();self.webhook_signature_key=os.environ.get("SQUARE_WEBHOOK_SIGNATURE_KEY","").strip();self.webhook_url=os.environ.get("SQUARE_WEBHOOK_URL","").strip()
        if not self.access_token or not self.location_id: raise PaymentProviderNotConfigured("SQUARE_ACCESS_TOKEN and SQUARE_LOCATION_ID are required")
    def create_checkout(self, **kwargs): raise PaymentProviderNotConfigured("Square checkout is reserved for physical sales in FabOS")
    def create_physical_payment(self, *, payment_id, amount_cents, currency, source_id, metadata):
        if not source_id: raise PaymentProviderError("Square source_id is required")
        body=json.dumps({"source_id":source_id,"idempotency_key":payment_id,"amount_money":{"amount":int(amount_cents),"currency":currency.upper()},"location_id":self.location_id,"reference_id":str(metadata["order_id"]),"note":"FabOS physical sale"}).encode("utf-8")
        request=urllib.request.Request(self.api_base+"/payments",data=body,method="POST",headers={"Authorization":"Bearer "+self.access_token,"Content-Type":"application/json","User-Agent":"FabOS/1.0"})
        try:
            with urllib.request.urlopen(request,timeout=15) as response: result=json.loads(response.read().decode("utf-8"))
        except Exception as exc: raise PaymentProviderError("Square payment request failed") from exc
        payment=result.get("payment") or {}
        return {"provider_payment_id":payment.get("id"),"checkout_url":None,"status":"paid" if payment.get("status")=="COMPLETED" else "pending","metadata":{**metadata,"square_payment_id":payment.get("id")}}
    def parse_webhook(self,payload,signature=None):
        if not self.webhook_signature_key or not self.webhook_url: raise PaymentProviderNotConfigured("SQUARE_WEBHOOK_SIGNATURE_KEY and SQUARE_WEBHOOK_URL are required")
        expected=base64_hmac_sha256(self.webhook_signature_key,self.webhook_url+(payload.decode("utf-8") if isinstance(payload,bytes) else payload))
        if not signature or not hmac.compare_digest(expected,str(signature)): raise PaymentProviderError("Invalid Square webhook signature")
        event=json.loads(payload.decode("utf-8") if isinstance(payload,bytes) else payload);event_type=str(event.get("type") or "");obj=((event.get("data") or {}).get("object") or {});payment=obj.get("payment") or {};status=None
        if event_type in {"payment.completed","payment.updated"} and str(payment.get("status") or "").upper()=="COMPLETED":
            status="paid";amount_money=payment.get("amount_money") or {};amount_cents=int(amount_money.get("amount") or 0)
        elif event_type=="payment.failed": status="failed"
        elif event_type in {"refund.created","refund.updated"} and str(payment.get("status") or "").upper()=="REFUNDED": status="refunded"
        return {"event_id":str(event.get("event_id") or ""),"event_type":event_type,"provider_payment_id":str(payment.get("id") or ""),"payment_id":"","order_id":str(payment.get("reference_id") or ""),"status":status,"amount_cents":amount_cents}


def base64_hmac_sha256(secret,message): return base64.b64encode(hmac.new(secret.encode("utf-8"),message.encode("utf-8"),hashlib.sha256).digest()).decode("ascii")

def _verify_stripe_signature(payload,signature,secret,tolerance=300):
    timestamp=None;signatures=[]
    for part in str(signature).split(","):
        key,_,value=part.partition("=")
        if key=="t": timestamp=value
        elif key=="v1" and value: signatures.append(value)
    if not timestamp or not signatures: raise PaymentProviderError("Invalid Stripe webhook signature")
    try: timestamp_int=int(timestamp)
    except ValueError as exc: raise PaymentProviderError("Invalid Stripe webhook timestamp") from exc
    if abs(int(time.time())-timestamp_int)>tolerance: raise PaymentProviderError("Expired Stripe webhook signature")
    signed_payload="%s.%s"%(timestamp,payload.decode("utf-8") if isinstance(payload,bytes) else payload);expected=hmac.new(secret.encode("utf-8"),signed_payload.encode("utf-8"),hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected,value) for value in signatures): raise PaymentProviderError("Invalid Stripe webhook signature")


class PaymentService:
    VALID_STATUSES={"created","pending","authorized","paid","failed","cancelled","refunded","partially_refunded","disputed"}
    def __init__(self,database,accounts,invoices): self.database=database;self.accounts=accounts;self.invoices=invoices;self._ensure_schema();self.provider=self._build_provider()
    def _ensure_schema(self):
        with self.database.connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS payment_transactions(id TEXT PRIMARY KEY,order_id TEXT NOT NULL UNIQUE REFERENCES orders(id) ON DELETE CASCADE,invoice_id TEXT REFERENCES invoices(id) ON DELETE SET NULL,customer_id TEXT REFERENCES customers(id) ON DELETE SET NULL,amount_cents INTEGER NOT NULL,currency TEXT NOT NULL DEFAULT 'USD',provider TEXT NOT NULL,provider_payment_id TEXT,checkout_url TEXT,status TEXT NOT NULL DEFAULT 'created',metadata_json TEXT NOT NULL DEFAULT '{}',created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_payment_transactions_customer ON payment_transactions(customer_id,created_at)");conn.execute("CREATE INDEX IF NOT EXISTS idx_payment_transactions_status ON payment_transactions(status,created_at)")
            conn.execute("""CREATE TABLE IF NOT EXISTS payment_webhook_events(id TEXT PRIMARY KEY,provider TEXT NOT NULL,event_type TEXT,payment_id TEXT,received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""");conn.commit()
    def _build_provider(self,name=None):
        name=(name or os.environ.get("FABOS_PAYMENT_PROVIDER","none")).strip().lower()
        if name in ("","none","unconfigured"): return UnconfiguredPaymentProvider()
        if name=="stripe": return StripePaymentProvider()
        if name=="square": return SquarePaymentProvider()
        raise ValueError("Unsupported payment provider: %s"%name)
    def _customer_for_order(self,user_id,order_id):
        user=self.accounts.get_user(user_id)
        if not user or not user["active"] or user["account_type"]!="customer": raise PermissionError("Customer account required")
        customer=self.accounts.customer_for_user(user_id)
        if not customer: raise PermissionError("Customer account is not linked to a customer record")
        with self.database.connect() as conn: order=conn.execute("SELECT * FROM orders WHERE id=? AND customer_id=?",(order_id,customer["id"])).fetchone()
        if not order: raise KeyError("Order not found")
        return customer,order
    def _prepare_transaction(self,order,customer_id,invoice_id,provider_name,channel):
        amount_cents=int(order["total_cents"] or 0)
        metadata={"order_id":str(order["id"]),"invoice_id":invoice_id,"channel":channel}
        with self.database.connect() as conn:
            existing=conn.execute("SELECT * FROM payment_transactions WHERE order_id=?",(order["id"],)).fetchone()
            if existing:
                status=str(existing["status"] or "").lower()
                if status not in {"failed","cancelled"} and not (status=="created" and str(existing["provider"] or "").lower()=="unconfigured"):
                    if str(existing["provider"] or "").lower() != str(provider_name or "").lower():
                        raise ValueError("A payment attempt already exists for this order with another payment provider")
                    return str(existing["id"]),amount_cents,metadata,False
                conn.execute("UPDATE payment_transactions SET invoice_id=?,customer_id=?,amount_cents=?,currency=?,provider=?,provider_payment_id=NULL,checkout_url=NULL,status='created',metadata_json=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(invoice_id,customer_id,amount_cents,"USD",provider_name,json.dumps(metadata,sort_keys=True),existing["id"]))
                conn.commit()
                return str(existing["id"]),amount_cents,metadata,True
            payment_id=str(uuid.uuid4())
            conn.execute("INSERT INTO payment_transactions(id,order_id,invoice_id,customer_id,amount_cents,currency,provider,status,metadata_json) VALUES(?,?,?,?,?,?,?,?,?)",(payment_id,order["id"],invoice_id,customer_id,amount_cents,"USD",provider_name,"created",json.dumps(metadata,sort_keys=True)))
            conn.commit()
            return payment_id,amount_cents,metadata,True
    def _new_transaction(self,order,customer_id,invoice_id,provider_name,channel):
        payment_id,amount_cents,metadata,created=self._prepare_transaction(order,customer_id,invoice_id,provider_name,channel)
        if not created: raise ValueError("A payment attempt is already active for this order")
        return payment_id,amount_cents,metadata
    def create_checkout(self,user_id,order_id):
        customer,order=self._customer_for_order(user_id,order_id)
        if str(order["status"] or "").lower() in {"cancelled","completed"}: raise ValueError("Payment is not available for this order")
        invoice_id,_=self.invoices.create_from_order(order_id)
        with self.database.connect() as conn:
            invoice=conn.execute("SELECT total_cents,status FROM invoices WHERE id=?", (invoice_id,)).fetchone()
        if not invoice or int(invoice["total_cents"] or 0) != int(order["total_cents"] or 0):
            raise ValueError("Order total no longer matches its invoice; payment cannot be started")
        provider=self._build_provider("stripe")
        payment_id,amount_cents,metadata,attempt_ready=self._prepare_transaction(order,customer["id"],invoice_id,provider.name,"customer-web")
        if not attempt_ready: return self.get(payment_id)
        try: result=provider.create_checkout(payment_id=payment_id,amount_cents=amount_cents,currency="USD",metadata=metadata)
        except PaymentProviderNotConfigured:
            with self.database.connect() as conn: conn.execute("UPDATE payment_transactions SET provider='unconfigured',status='created',updated_at=CURRENT_TIMESTAMP WHERE id=?",(payment_id,));conn.commit()
            return {"id":payment_id,"order_id":order_id,"invoice_id":invoice_id,"amount_cents":amount_cents,"currency":"USD","provider":provider.name,"status":"not_configured","payment_required":amount_cents>0,"checkout_url":None}
        except PaymentProviderError: self._set_status(payment_id,"failed");raise
        self._update_gateway_fields(payment_id,result,str(result.get("status") or "pending"));return self.get(payment_id)
    def record_physical_payment(self,order_id,source_id,provider_name="square"):
        with self.database.connect() as conn: order=conn.execute("SELECT * FROM orders WHERE id=?",(order_id,)).fetchone()
        if not order: raise KeyError("Order not found")
        if str(order["status"] or "").lower() in {"cancelled","completed"}: raise ValueError("Payment is not available for this order")
        provider=self._build_provider(provider_name)
        invoice_id,_=self.invoices.create_from_order(order_id)
        payment_id,amount_cents,metadata,attempt_ready=self._prepare_transaction(order,order["customer_id"],invoice_id,provider.name,"physical")
        if not attempt_ready: return self.get(payment_id)
        try: result=provider.create_physical_payment(payment_id=payment_id,amount_cents=amount_cents,currency="USD",source_id=source_id,metadata=metadata)
        except PaymentProviderError: self._set_status(payment_id,"failed");raise
        self._update_gateway_fields(payment_id,result,str(result.get("status") or "pending"));
        if str(result.get("status") or "").lower()=="paid": self._settle_transaction(payment_id,"paid",result.get("provider_payment_id"))
        return self.get(payment_id)
    def handle_webhook(self,payload,signature=None,provider_name=None):
        provider=self._build_provider(provider_name);event=provider.parse_webhook(payload,signature);event_id=event.get("event_id")
        if not event_id: raise PaymentProviderError("Webhook event has no id")
        # Claim the event before processing so concurrent deliveries cannot settle it twice.
        # If processing fails, release the claim so the provider can safely retry.
        with self.database.connect() as conn:
            existing=conn.execute("SELECT 1 FROM payment_webhook_events WHERE id=?",(event_id,)).fetchone()
            if existing: return {"processed":False,"duplicate":True,"event_id":event_id}
            conn.execute("INSERT INTO payment_webhook_events(id,provider,event_type,payment_id) VALUES(?,?,?,?)",(event_id,provider.name,event.get("event_type"),event.get("payment_id") or event.get("provider_payment_id")));conn.commit()
        try:
            payment_id=event.get("payment_id")
            if not payment_id and event.get("provider_payment_id"):
                with self.database.connect() as conn:
                    row=conn.execute("SELECT id FROM payment_transactions WHERE provider_payment_id=? ORDER BY created_at DESC LIMIT 1",(event["provider_payment_id"],)).fetchone();payment_id=row["id"] if row else None
            if not payment_id and event.get("order_id"):
                with self.database.connect() as conn:
                    row=conn.execute("SELECT id FROM payment_transactions WHERE order_id=? ORDER BY created_at DESC LIMIT 1",(event["order_id"],)).fetchone();payment_id=row["id"] if row else None
            if payment_id and event.get("status") in self.VALID_STATUSES:
                if event.get("status") == "paid":
                    with self.database.connect() as conn:
                        payment_row=conn.execute("SELECT amount_cents FROM payment_transactions WHERE id=?",(payment_id,)).fetchone()
                    provider_amount=event.get("amount_cents")
                    if provider_amount is None or int(provider_amount) <= 0:
                        raise PaymentProviderError("Paid webhook is missing a valid amount")
                    if not payment_row or int(payment_row["amount_cents"] or 0) != int(provider_amount):
                        raise PaymentProviderError("Paid webhook amount does not match the FabOS payment amount")
                self._set_status(payment_id,event["status"],provider_payment_id=event.get("provider_payment_id"))
            return {"processed":True,"duplicate":False,"event_id":event_id,"status":event.get("status")}
        except Exception:
            with self.database.connect() as conn:
                conn.execute("DELETE FROM payment_webhook_events WHERE id=?",(event_id,));conn.commit()
            raise
    def _update_gateway_fields(self,payment_id,result,status):
        with self.database.connect() as conn: conn.execute("UPDATE payment_transactions SET provider_payment_id=?,checkout_url=?,status=?,metadata_json=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(result.get("provider_payment_id"),result.get("checkout_url"),status,json.dumps(result.get("metadata") or {},sort_keys=True),payment_id));conn.commit()
    def _set_status(self,payment_id,status,provider_payment_id=None):
        if status not in self.VALID_STATUSES: raise ValueError("Unsupported payment status: %s"%status)
        with self.database.connect() as conn: row=conn.execute("SELECT * FROM payment_transactions WHERE id=?",(payment_id,)).fetchone()
        if not row: raise KeyError("Payment transaction not found")
        current=str(row["status"] or "created").lower()
        # Provider webhooks can arrive out of order. Never let a late failure/cancel
        # overwrite a payment that has already been confirmed paid or refunded.
        transitions={
            "created":{"pending","authorized","paid","failed","cancelled"},
            "pending":{"authorized","paid","failed","cancelled"},
            "authorized":{"paid","failed","cancelled"},
            "paid":{"partially_refunded","refunded","disputed"},
            "partially_refunded":{"refunded","disputed"},
            "failed":set(),
            "cancelled":set(),
            "refunded":set(),
            "disputed":set(),
        }
        if status!=current and status not in transitions.get(current,set()):
            return
        with self.database.connect() as conn:
            if provider_payment_id: conn.execute("UPDATE payment_transactions SET status=?,provider_payment_id=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(status,provider_payment_id,payment_id))
            else: conn.execute("UPDATE payment_transactions SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(status,payment_id))
            conn.commit()
        if status=="paid": self._settle_transaction(payment_id,status,provider_payment_id)
    def _settle_transaction(self,payment_id,status,provider_payment_id=None):
        with self.database.connect() as conn: row=conn.execute("SELECT * FROM payment_transactions WHERE id=?",(payment_id,)).fetchone()
        if not row or status!="paid": return
        invoice_id=row["invoice_id"];amount=int(row["amount_cents"] or 0);reference=provider_payment_id or row["provider_payment_id"] or payment_id
        try:
            with self.database.connect() as conn: exists=conn.execute("SELECT 1 FROM payments WHERE invoice_id=? AND reference=? LIMIT 1",(invoice_id,reference)).fetchone()
        except Exception: exists=None
        if not exists:
            self.invoices.record_payment(invoice_id,amount,method=row["provider"],reference=reference,notes="Gateway payment reconciled by FabOS")
        with self.database.connect() as conn:
            current=conn.execute("SELECT status FROM orders WHERE id=?",(row["order_id"],)).fetchone()
            if current and str(current["status"] or "").lower()=="pending": conn.execute("UPDATE orders SET status='confirmed' WHERE id=?",(row["order_id"],));conn.commit()
    def get(self,payment_id):
        with self.database.connect() as conn: row=conn.execute("SELECT * FROM payment_transactions WHERE id=?",(payment_id,)).fetchone()
        if not row: raise KeyError("Payment transaction not found")
        return self._json(row)
    @staticmethod
    def _json(row):
        if row is None:return None
        if hasattr(row,"keys"):return {str(key):row[key] for key in row.keys()}
        return dict(row)
