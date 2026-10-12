import json
from src.agent_workflow import propose_query, evidence_facts
from src.contracts import QueryGateway


class StubPlanner:
    available = True
    model = "test-planner"
    def __init__(self, result):
        self.result = result
    def chat(self, system, user):
        self.input = json.loads(user)
        return self.result


def test_model_proposes_but_never_executes(loop):
    client = StubPlanner(json.dumps({"query": "8月华东订单量是多少？", "rationale": "聚合计数", "limitations": []}))
    proposal = propose_query(client, "看8月华东订单情况", loop.aligner.metrics)
    assert proposal["original_goal"] == "看8月华东订单情况"
    assert proposal["execution"] == "not_executed" and proposal["review_required"]
    assert "catalogue" in client.input and "rows" not in client.input
    gateway = QueryGateway(loop)
    contract = gateway.preview(proposal["query"])["contract"]
    receipt = gateway.execute(contract)["evidence"]
    facts = evidence_facts(receipt)
    assert facts["facts"] == receipt["result"]["rows"]


def test_raw_sql_proposal_cannot_bypass_semantic_gateway(loop):
    client = StubPlanner(json.dumps({"query": "DROP TABLE orders", "rationale": "invalid", "limitations": []}))
    proposal = propose_query(client, "订单量", loop.aligner.metrics)
    assert QueryGateway(loop).preview(proposal["query"])["type"] == "insufficient"


def test_bad_model_output_is_not_executed(loop):
    proposal = propose_query(StubPlanner('{"sql":"DROP TABLE orders"}'), "订单量", loop.aligner.metrics)
    assert proposal["type"] == "error"


def test_unavailable_model_is_reported(loop):
    client = StubPlanner("")
    client.available = False
    assert propose_query(client, "订单量", loop.aligner.metrics)["type"] == "unavailable"
