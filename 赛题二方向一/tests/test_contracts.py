"""Contract failures must be tested across data, meaning, scope and result mutations."""
import copy
import json
import duckdb
import pytest
from src.cache import SemanticCache
from src.contracts import QueryGateway, revisions
from src.loop import Clarification, QueryLoop


@pytest.fixture
def writable(conn):
    fresh = duckdb.connect()
    for table in ("orders", "shipments", "products", "customers", "carriers", "meta"):
        fresh.register("source_frame", conn.execute(f"SELECT * FROM {table}").fetchdf())
        fresh.execute(f"CREATE TABLE {table} AS SELECT * FROM source_frame")
        fresh.unregister("source_frame")
    yield fresh
    fresh.close()


def test_preview_never_defaults_ambiguous_meaning(loop):
    out = QueryGateway(loop).preview("最近苹果GMV是多少？")
    assert out["type"] == "clarification"
    assert {p["id"] for p in out["points"]} == {"time", "entity", "variant"}


@pytest.mark.parametrize("choices", [{}, {"variant": -1}, {"variant": 99}, {"variant": True},
                                    {"variant": "0"}, {"variant": 0, "time": 0}])
def test_resolution_rejects_incomplete_or_invalid_choices(loop, choices):
    clar = loop.ask("8月GMV是多少？")
    ans = loop.resolve(clar, choices)
    assert ans.type == "error"
    assert isinstance(clar, Clarification) and clar.alignment.variant_id is None


def test_resolution_does_not_mutate_shared_plan(loop):
    clar = loop.ask("8月GMV是多少？")
    gross = loop.resolve(clar, {"variant": 0})
    net = loop.resolve(clar, {"variant": 2})
    assert gross.value > net.value
    assert clar.alignment.variant_id is None and clar.alignment.clarify


def test_full_multiline_result_replays(loop):
    g = QueryGateway(loop)
    ready = g.preview("8月华为和苹果订单量对比")
    assert ready["type"] == "ready"
    answer = g.execute(ready["contract"])
    assert answer["type"] == "answer"
    receipt = answer["evidence"]
    assert len(receipt["result"]["rows"]) == 2
    assert g.replay(json.loads(json.dumps(receipt, allow_nan=False)))["matches"] is True


def test_contract_sql_tampering_is_rejected(loop):
    g = QueryGateway(loop)
    contract = g.preview("8月订单量是多少？")["contract"]
    contract["query"]["template"] = "DROP TABLE orders"
    assert g.execute(contract)["status"] == "invalid_contract"


def test_result_tampering_is_rejected(loop):
    g = QueryGateway(loop)
    receipt = g.execute(g.preview("8月订单量是多少？")["contract"])["evidence"]
    receipt["result"]["rows"][0]["value"] = -1
    assert g.replay(receipt)["status"] == "invalid_receipt"


def test_scope_is_enforced_at_execution_not_just_preview(loop):
    public = QueryGateway(loop)
    east = QueryGateway(loop, ("华东",))
    assert east.preview("8月华南订单量是多少？")["type"] == "error"
    southern_contract = public.preview("8月华南订单量是多少？")["contract"]
    assert east.execute(southern_contract)["status"] == "invalid_contract"
    regional = east.preview("8月订单量是多少？")["contract"]
    assert regional["plan"]["filters"]["region"] == "华东"
    assert east.execute(regional)["type"] == "answer"


def test_data_change_invalidates_contract_and_actual_connection_cache(writable):
    l = QueryLoop(writable, cache=SemanticCache())
    g = QueryGateway(l)
    ready = g.preview("8月净实付GMV是多少？")
    first = l.ask("8月净实付GMV是多少？")
    writable.execute("UPDATE orders SET pay_amount = pay_amount + 1 WHERE order_time >= '2026-08-01' AND order_time < '2026-09-01'")
    assert g.execute(ready["contract"])["status"] == "stale_contract"
    changed = l.ask("8月净实付GMV是多少？")
    assert changed.value > first.value
    assert l.cache.stats.hits == 0


def test_semantic_content_change_invalidates_contract_even_if_mtime_preserved(conn, ontology_copy):
    import os
    l = QueryLoop(conn, ontology_dir=ontology_copy)
    g = QueryGateway(l)
    ready = g.preview("8月订单量是多少？")
    p = ontology_copy / "metrics.yaml"
    stat = p.stat()
    p.write_text(p.read_text(encoding="utf-8") + "\n# revision probe\n", encoding="utf-8")
    os.utime(p, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert g.execute(ready["contract"])["status"] == "stale_contract"


def test_duplicate_relation_blocks_before_answer(writable):
    l = QueryLoop(writable)
    writable.execute("INSERT INTO shipments SELECT * FROM shipments LIMIT 1")
    answer = l.ask("8月订单量是多少？")
    assert answer.type == "insufficient" and answer.trust["状态"] == "blocked_by_quality"
    assert answer.evidence == {}


def test_cached_nested_results_are_independent(conn):
    l = QueryLoop(conn, cache=SemanticCache())
    first = l.ask("8月华为和苹果订单量对比")
    original = copy.deepcopy(first.evidence)
    first.evidence["result"]["rows"][0]["metric"] = -9
    first.df.iloc[0, 1] = -9
    hit = l.ask("8月华为和苹果订单量对比")
    assert hit.evidence == original
    assert hit.df.iloc[0, 1] > 0


def test_automatic_choices_are_visible_in_evidence(loop):
    ans = loop.ask("8月GMV是多少？", auto_resolve=True)
    assert ans.evidence["resolution"] == "assumed_first_option"
    assert "未经用户确认" in ans.trust["口径决策"]
