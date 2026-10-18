"""HTTP assertions across the real Gateway and independent service databases."""
import json
import secrets
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class Api:
    def __init__(self, base: str, token: str | None = None):
        self.base, self.token = base, token

    def call(self, method: str, path: str, payload=None, headers=None):
        values = {"Content-Type": "application/json", **(headers or {})}
        if self.token: values["Authorization"] = "Bearer " + self.token
        request = Request(self.base + path, data=json.dumps(payload).encode() if payload is not None else None,
                          method=method, headers=values)
        try: response = urlopen(request, timeout=12)
        except HTTPError as error: response = error
        with response:
            return response.status, json.load(response), dict(response.headers)

    def ok(self, method: str, path: str, payload=None, headers=None):
        status, body, response_headers = self.call(method, path, payload, headers)
        assert status == 200 and body.get("code") == 0, (path, status, body.get("code"))
        return body, response_headers


class Checks:
    def __init__(self, base: str, model):
        self.public, self.model = Api(base), model
        self.results = []

    def record(self, name: str):
        self.results.append({"name": name, "passed": True})
        print("PASS", name, flush=True)

    def login(self, username: str, password: str) -> Api:
        body, _ = self.public.ok("POST", "/api/user/login", {"username": username, "password": password})
        return Api(self.public.base, body["data"]["token"])

    def balance(self, api: Api) -> int:
        return api.ok("GET", "/api/user/points")[0]["data"]["balance"]

    def verify_settlement(self, api: Api, body: dict, headers: dict, before: int, price: int, cost: int, capability_id: int):
        data = body["data"]
        assert data["capability_id"] == capability_id
        assert data["price_per_call"] == price and data["cost"] == cost
        assert body["requestId"] == data["request_id"]
        header_id = next((v for k, v in headers.items() if k.lower() == "x-request-id"), None)
        assert header_id == data["request_id"] and header_id != "forged-by-browser"
        assert before - self.balance(api) == cost
        records = api.ok("GET", "/api/billing/records?page_size=100")[0]["data"]["list"]
        record = next(row for row in records if row["request_id"] == data["request_id"])
        assert record["cost"] == cost and record["capability_id"] == capability_id
        assert record["call_status"] == data["call_status"] and record["duration_ms"] == data["duration_ms"]
        logs = api.ok("GET", "/api/user/points/logs?direction=out&page_size=100")[0]["data"]["list"]
        log = [row for row in logs if row["request_id"] == data["request_id"]]
        assert (len(log) == 1 and log[0]["amount"] == cost) if cost else not log

    def reject_without_model(self, api: Api, payload: dict, expected: int):
        model_count, before = len(self.model.calls), self.balance(api)
        bill_count = api.ok("GET", "/api/billing/records")[0]["data"]["total"]
        _, body, _ = api.call("POST", "/api/chat/completions", payload)
        assert body["code"] == expected, body.get("code")
        assert len(self.model.calls) == model_count and self.balance(api) == before
        assert api.ok("GET", "/api/billing/records")[0]["data"]["total"] == bill_count

    def run(self):
        username, password = "qa" + secrets.token_hex(5), "qa-leader-integration-123"
        self.username, self.password = username, password
        registered, _ = self.public.ok("POST", "/api/user/register", {"username": username, "password": password})
        self.user_id = registered["data"]["user_id"]
        self.user = self.login(username, password)
        self.record("real registration and signed JWT login")
        market = self.public.ok("GET", "/api/capability/market?page_size=100")[0]["data"]["list"]
        prices = {row["id"]: row["price_per_call"] for row in market}
        assert prices[1] == 5 and prices[2] == 3 and 3 not in prices
        self.record("published catalog and registered prices")
        status, _, _ = self.public.call("POST", "/api/chat/completions", {"messages": [{"role": "user", "content": "unauthenticated"}]})
        assert status == 401
        self.record("unauthenticated execution rejected")
        profile = self.user.ok("GET", "/api/user/profile", headers={"X-User-Id": "1", "role": "admin", "X-User-Role": "admin"})[0]["data"]
        assert profile.get("id") == self.user_id or profile.get("user_id") == self.user_id
        self.record("forged identity cannot change current user")

        before = self.balance(self.user)
        chat, headers = self.user.ok("POST", "/api/chat/completions", {
            "capability_id": 1, "input": {"messages": [{"role": "user", "content": "QA chat request"}]}},
            {"X-Request-Id": "forged-by-browser"})
        assert not chat["data"]["mock"]
        self.verify_settlement(self.user, chat, headers, before, 5, 5, 1)
        self.record("chat catalog price = bill = points log = balance delta, same requestId")
        self.session_id = chat["data"]["session_id"]
        self.first_chat = chat["data"]
        history = self.user.ok("GET", f"/api/chat/sessions/{self.session_id}/messages")[0]["data"]
        assert history["total"] == 2
        self.record("real conversation persistence")

        text = "团队完成了公共环境。下一步完善摘要功能并验证按能力定价。"
        before = self.balance(self.user)
        summary, headers = self.user.ok("POST", "/api/chat/completions", {"capability_id": 2, "input": {"text": text, "max_length": 80}})
        self.verify_settlement(self.user, summary, headers, before, 3, 3, 2)
        sent = self.model.calls[-1]["messages"]
        assert sent[-1] == {"role": "user", "content": text}
        assert sent[0]["role"] == "system" and "80" in sent[0]["content"] and "摘要" in sent[0]["content"]
        self.record("summary adapter prompt and independent 3-point settlement")

        for name, payload, code in [
            ("schema mismatch", {"capability_id": 2, "input": {"messages": []}}, 2001),
            ("unknown capability", {"capability_id": 99999, "input": {"text": "x"}}, 2002),
            ("draft capability", {"capability_id": 3, "input": {"image_url": "x"}}, 2002),
            ("unsupported online adapter", {"capability_id": 4, "input": {}}, 2008),
            ("forged unit price", {"capability_id": 1, "price_per_call": 0, "input": {}}, 2001),
        ]:
            self.reject_without_model(self.user, payload, code)
            self.record(name + ": no model, no bill, no points change")
        poor = self.login("demopoor", "demo123456")
        self.reject_without_model(poor, {"messages": [{"role": "user", "content": "insufficient"}]}, 3001)
        self.record("insufficient points rejected before model")

        for marker, error_code in [("[test-timeout]", 5001), ("[test-malformed]", 5002)]:
            before = self.balance(self.user)
            degraded, headers = self.user.ok("POST", "/api/chat/completions", {"messages": [{"role": "user", "content": marker}]})
            assert degraded["data"]["degraded"] and degraded["data"]["error_code"] == error_code
            self.verify_settlement(self.user, degraded, headers, before, 5, 0, 1)
            self.record(f"real model adapter degradation {error_code}: zero charge with bill")
        _, denied, _ = poor.call("GET", f"/api/chat/sessions/{self.session_id}/messages")
        assert denied["code"] == 4004
        self.record("cross-user history rejected")
        for path in ["/internal/user/check", "/user-service/internal/user/check"]:
            assert self.user.call("GET", path)[0] == 403
        self.record("external internal paths blocked")
        return self.results

    def verify_catalog_changes(self, sql):
        sql("UPDATE capability_db.t_capability SET status='offline' WHERE id=1")
        self.reject_without_model(self.user, {"messages": [{"role": "user", "content": "offline"}]}, 2002)
        self.record("newly offline capability rejected before model")
        sql("UPDATE capability_db.t_capability SET status='online',price_per_call=7 WHERE id=1")
        before = self.balance(self.user)
        body, headers = self.user.ok("POST", "/api/chat/completions",
            {"messages": [{"role": "user", "content": "fresh catalog price"}]})
        self.verify_settlement(self.user, body, headers, before, 7, 7, 1)
        self.record("catalog price change is read freshly and settled at 7 points")
        sql("UPDATE capability_db.t_capability SET price_per_call=5 WHERE id=1")

    def verify_disabled_account(self, sql):
        count, before = len(self.model.calls), self.balance(self.user)
        bills = self.user.ok("GET", "/api/billing/records")[0]["data"]["total"]
        sql(f"UPDATE user_db.t_user SET status='disabled' WHERE id={int(self.user_id)}")
        _, body, _ = self.user.call("POST", "/api/chat/completions",
            {"messages": [{"role": "user", "content": "disabled account"}]})
        assert body["code"] == 1005 and len(self.model.calls) == count
        sql(f"UPDATE user_db.t_user SET status='normal' WHERE id={int(self.user_id)}")
        assert self.balance(self.user) == before
        assert self.user.ok("GET", "/api/billing/records")[0]["data"]["total"] == bills
        self.record("currently disabled account rejected despite a previously valid JWT")

    def verify_gateway_exchange(self):
        for path in ["/api/user/apikeys/exchange/", "/api/user/apikeys/exchange/extra"]:
            assert self.public.call("POST", path, {})[0] == 401
        assert self.public.call("GET", "/api/user/apikeys/exchange")[0] == 401
        for attempt in range(11):
            status, body, headers = self.public.call("POST", "/api/user/apikeys/exchange", {})
            assert next((value for key, value in headers.items() if key.lower() == "cache-control"), None) == "no-store"
            if attempt < 10:
                assert status != 401 and status != 429
            else:
                assert status == 429 and body["code"] == 4001
        self.record("Gateway exchange exact POST whitelist, no-store and 10/minute limit")

    def verify_strict_mode(self, strict_base: str):
        """A missing member interface must cause a clear error, never a silent fallback."""
        count = len(self.model.calls)
        api = Api(strict_base)
        _, body, _ = api.call("POST", "/api/chat/completions",
            {"messages": [{"role": "user", "content": "strict integration probe"}]},
            headers={"X-User-Id": str(self.user_id), "X-User-Name": self.username,
                     "X-Request-Id": "strict-internal-probe"})
        if body["code"] == 4002:
            assert len(self.model.calls) == count
            self.record("strict internal mode: missing catalog contract fails closed before model")
            return False
        assert body["code"] == 0
        assert body["data"]["catalog_source"] == "internal"
        self.record("strict internal catalog chain available")
        return True
