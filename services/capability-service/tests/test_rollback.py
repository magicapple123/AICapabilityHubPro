"""D5 上架体验：按审计快照回滚，回滚本身也留痕。"""

from tests.conftest import USER_HEADERS


def _audit(client, **params):
    return client.get("/api/capability/audit", headers=USER_HEADERS,
                      params={"page_size": 50, **params}).json()["data"]["list"]


def test_rollback_restores_price_and_writes_its_own_audit(qa):
    category = qa.category()
    created = qa.create_capability_raw(category["id"], code=qa.code("rb"), price=7)
    capability_id = created["data"]["id"]

    qa.client.put(f"/api/capability/{capability_id}", headers=USER_HEADERS,
                  json={"price_per_call": 9})
    update_log = [r for r in _audit(qa.client, resource_type="capability",
                                    resource_id=capability_id, action="update")][0]

    body = qa.client.post(f"/api/capability/{capability_id}/rollback",
                          headers=USER_HEADERS, json={"audit_id": update_log["id"]}).json()
    assert body["code"] == 0, body

    detail = qa.client.get(f"/internal/capability/{capability_id}",
                           headers=USER_HEADERS).json()["data"]
    assert detail["price_per_call"] == 7

    rollback_logs = _audit(qa.client, resource_type="capability",
                           resource_id=capability_id, action="rollback")
    assert rollback_logs and rollback_logs[0]["after_json"]["price_per_call"] == 7


def test_rollback_rejects_mismatched_capability(qa):
    category = qa.category()
    first = qa.create_capability_raw(category["id"], code=qa.code("rb1"))
    second = qa.create_capability_raw(category["id"], code=qa.code("rb2"))
    log = _audit(qa.client, resource_type="capability", resource_id=first["data"]["id"],
                 action="create")[0]
    body = qa.client.post(f"/api/capability/{second['data']['id']}/rollback",
                          headers=USER_HEADERS, json={"audit_id": log["id"]}).json()
    assert body["code"] == 2001


def test_rollback_rejects_bad_audit_id(qa):
    category = qa.category()
    created = qa.create_capability_raw(category["id"], code=qa.code("rb3"))
    body = qa.client.post(f"/api/capability/{created['data']['id']}/rollback",
                          headers=USER_HEADERS, json={"audit_id": 0}).json()
    assert body["code"] == 2001
