"""Objective tasks with private deterministic oracles and sandboxed expression evaluation.
No untrusted Python source is ever executed. No external calls, files or side effects.
"""
import ast
import operator
from .model import Task, ProtocolViolation

BINOPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
          ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod}


def _safe_expr(expr: str, variables: dict) -> int:
    """Evaluate a tiny arithmetic DSL, not Python eval/exec."""
    if len(expr) > 512:
        raise ProtocolViolation("expression too long")
    tree = ast.parse(expr, mode="eval")
    if len(list(ast.walk(tree))) > 80:
        raise ProtocolViolation("expression too complex")

    def visit(node, depth=0):
        if depth > 20:
            raise ProtocolViolation("expression too deep")
        if isinstance(node, ast.Expression):
            return visit(node.body, depth+1)
        if isinstance(node, ast.Constant) and type(node.value) is int:
            if abs(node.value) > 1_000_000_000:
                raise ProtocolViolation("out of range")
            return node.value
        if isinstance(node, ast.Name) and node.id in variables:
            return variables[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in BINOPS:
            left, right = visit(node.left, depth+1), visit(node.right, depth+1)
            if type(node.op) in (ast.FloorDiv, ast.Mod) and right == 0:
                raise ProtocolViolation("division by zero")
            r = BINOPS[type(node.op)](left, right)
            if abs(r) > 1_000_000_000_000:
                raise ProtocolViolation("result out of range")
            return r
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("min", "max") and len(node.args) == 2 and not node.keywords:
            a, b = visit(node.args[0], depth+1), visit(node.args[1], depth+1)
            return min(a,b) if node.func.id == "min" else max(a,b)
        raise ProtocolViolation(f"forbidden expression element: {type(node).__name__}")
    return visit(tree)


def evaluate(task: Task, artifact: dict) -> tuple[bool, str]:
    """Returns (conforms, reason); the private oracle is NOT visible to the agent."""
    try:
        if task.family == "software":
            expr = artifact["expression"]
            if not isinstance(expr, str):
                return False, "not an expression"
            for case in task.evidence["private_tests"]:
                actual = _safe_expr(expr, case["inputs"])
                if actual != case["expected"]:
                    return False, "hidden regression test failed"
            return True, "all hidden regression tests passed"
        if task.family == "reconciliation":
            if set(artifact) != {"net_cents", "posted_count"}:
                return False, "wrong schema"
            posted = [x for x in task.evidence["entries"] if x["status"] == "posted"]
            return (artifact["net_cents"] == sum(x["amount_cents"] for x in posted)
                    and artifact["posted_count"] == len(posted), "ledger calculation")
        if task.family == "procurement":
            order = task.evidence
            shipping = order["shipment"]
            # Invoice amount is computed from accepted, not ordered, stock.
            if shipping["accepted_units"] > order["units"] or shipping["accepted_units"] < 0:
                return False, "inconsistent purchase-order/shipment evidence"
            if shipping["inspection"] not in ("pass", "partial"):
                return False, "shipment not accepted"
            sub = shipping["accepted_units"] * order["unit_price_cents"]
            total = sub + (sub * order["tax_bps"] + 9999) // 10000
            return (set(artifact) == {"order_id", "supplier", "sku", "units", "invoice_cents", "receipt_id"}
                    and artifact["order_id"] == order["order_id"]
                    and artifact["supplier"] == order["supplier"]
                    and artifact["sku"] == order["sku"]
                    and type(artifact["units"]) is int
                    and artifact["units"] == shipping["accepted_units"]
                    and type(artifact["invoice_cents"]) is int
                    and artifact["invoice_cents"] == total
                    and artifact["receipt_id"] == shipping["receipt_id"], "purchase order and accepted shipment conformance")
        if task.family == "api_service":
            e = task.evidence
            return (set(artifact) == {"request_id", "source_count", "status", "result_sha256"}
                    and artifact["request_id"] == e["request_id"]
                    and type(artifact["source_count"]) is int
                    and artifact["source_count"] == e["expected_source_count"]
                    and artifact["status"] == e["allowed_status"]
                    and artifact["result_sha256"] == e["result_sha256"], "service output digest and request binding")
        if task.family == "grounded_claims":
            claims = artifact["claims"]
            if not isinstance(claims, list) or any(not isinstance(c, str) for c in claims):
                return False, "invalid claims type"
            valid_claims = set(task.evidence["supported_claims"])
            mandatory = set(task.evidence["required_claims"])
            return (len(claims) == len(set(claims)) and set(claims).issubset(valid_claims)
                    and mandatory.issubset(set(claims)), "evidence-supported claims")
        raise ProtocolViolation("unknown task family")
    except (ProtocolViolation, ValueError, TypeError, KeyError, OverflowError, SyntaxError):
        return False, "invalid or untrusted artifact"


def make_tasks() -> list[Task]:
    return [
        Task(task_id="code-tax-01", family="software", price=100,
             specification="Return final price in cents after tax, rounding tax UP to next cent. Accept only tested expression.",
             evidence={"private_tests": [
                 {"inputs":{"subtotal": 123, "tax_bps": 750}, "expected": 133},
                 {"inputs":{"subtotal": 100, "tax_bps": 0}, "expected": 100},
                 {"inputs":{"subtotal": 1, "tax_bps": 100}, "expected": 2},
                 {"inputs":{"subtotal": 250, "tax_bps": 900}, "expected": 273},
                 {"inputs":{"subtotal": 999, "tax_bps": 100}, "expected": 1009}]},
             good_work={"expression": "subtotal + ((subtotal * tax_bps + 9999) // 10000)"},
             bad_work={"expression": "subtotal + ((subtotal * tax_bps) // 10000)"}),
        Task(task_id="code-refund-02", family="software", price=100,
             specification="Prevent negative wallet balance when subtracting debit from balance.",
             evidence={"private_tests": [
                 {"inputs":{"balance": 100, "debit": 15}, "expected": 85},
                 {"inputs":{"balance": 10, "debit": 90}, "expected": 0},
                 {"inputs":{"balance": 0, "debit": 0}, "expected": 0},
                 {"inputs":{"balance": 35, "debit": 35}, "expected": 0}]},
             good_work={"expression":"max(0, balance - debit)"},
             bad_work={"expression":"balance - debit"}),
        Task(task_id="reconcile-01", family="reconciliation", price=100,
             specification="Sum *posted* debit and credit entries and return posted entry count. Pending entries excluded.",
             evidence={"entries":[
                 {"id":"tx1","amount_cents":2500,"status":"posted"},
                 {"id":"tx2","amount_cents":-725,"status":"posted"},
                 {"id":"tx3","amount_cents":-150,"status":"posted"},
                 {"id":"tx4","amount_cents":4000,"status":"pending"},
                 {"id":"tx5","amount_cents":-35,"status":"posted"}]},
             good_work={"net_cents":1590,"posted_count":4},
             bad_work={"net_cents":1591,"posted_count":4}),
        Task(task_id="reconcile-02", family="reconciliation", price=100,
             specification="Reconcile posted ledger entries; do not include pending transactions.",
             evidence={"entries":[
                 {"id":"b1","amount_cents":10000,"status":"posted"},
                 {"id":"b2","amount_cents":-2500,"status":"posted"},
                 {"id":"b3","amount_cents":-1500,"status":"pending"},
                 {"id":"b4","amount_cents":-1100,"status":"posted"}]},
             good_work={"net_cents":6400,"posted_count":3},
             bad_work={"net_cents":4900,"posted_count":4}),
        Task(task_id="evidence-01", family="grounded_claims", price=100,
             specification="Report only supported evidence claims. Claim that a performance benchmark passed is forbidden without evidence.",
             evidence={"supported_claims":["checksum verified", "receipt dated", "operator authenticated"],
                       "required_claims":["checksum verified", "receipt dated"]},
             good_work={"claims":["checksum verified", "receipt dated"]},
             bad_work={"claims":["checksum verified", "receipt dated", "benchmark passed"]}),
        Task(task_id="evidence-02", family="grounded_claims", price=100,
             specification="Determine only the verifiable facts about a supplier's response.",
             evidence={"supported_claims":["contract signed", "delivery receipt recorded"],
                       "required_claims":["contract signed"]},
             good_work={"claims":["contract signed", "delivery receipt recorded"]},
             bad_work={"claims":["contract signed", "risk assessment completed"]}),
    ]
