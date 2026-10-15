"""New multi-document paid-service tasks. Data are synthetic and all verification is local.

Every task stores immutable ground-truth records in Task.evidence. The auditor sees
contract terms and provider artifacts, but does not see the oracle's conformance flag.
"""
from __future__ import annotations
from .model import Task, ProtocolViolation, digest
from .tasks import make_tasks, evaluate


def make_study_tasks() -> list[Task]:
    jobs = make_tasks()
    jobs.extend([
        Task(
            task_id="procure-sensor-01",family="procurement",price=120,
            specification="Purchase order PO-SN-214: deliver 6 calibrated sensors at 1,900 cents each; 7.5% tax rounded up; only supplier SUP-NTU-17 may invoice. Shipment must be accepted before invoicing.",
            evidence={"order_id":"PO-SN-214","supplier":"SUP-NTU-17","sku":"SENSOR-7",
                      "units":6,"unit_price_cents":1900,"tax_bps":750,
                      "shipment":{"receipt_id":"REC-214","accepted_units":6,"inspection":"pass"}},
            good_work={"order_id":"PO-SN-214","supplier":"SUP-NTU-17","sku":"SENSOR-7",
                       "units":6,"invoice_cents":12255,"receipt_id":"REC-214"},
            bad_work={"order_id":"PO-SN-214","supplier":"SUP-NTU-17","sku":"SENSOR-7",
                      "units":6,"invoice_cents":12455,"receipt_id":"REC-214"}),
        Task(
            task_id="procure-damaged-02",family="procurement",price=140,
            specification="Invoice hardware only after warehouse acceptance: 5 router modules at 2,300 cents each, tax 0%, supplier SUP-NTU-22. Rejected units may not be charged.",
            evidence={"order_id":"PO-WH-330","supplier":"SUP-NTU-22","sku":"RADIO-8",
                      "units":5,"unit_price_cents":2300,"tax_bps":0,
                      "shipment":{"receipt_id":"REC-330","accepted_units":4,"inspection":"partial"}},
            good_work={"order_id":"PO-WH-330","supplier":"SUP-NTU-22","sku":"RADIO-8",
                       "units":4,"invoice_cents":9200,"receipt_id":"REC-330"},
            bad_work={"order_id":"PO-WH-330","supplier":"SUP-NTU-22","sku":"RADIO-8",
                      "units":5,"invoice_cents":11500,"receipt_id":"REC-330"}),
        Task(
            task_id="api-telemetry-01",family="api_service",price=80,
            specification="Data provider delivers sensor anomaly batch for BATCH-A22; result digest, batch identifier and source count must match the independently recorded service request.",
            evidence={"request_id":"BATCH-A22","expected_source_count":22,
                      "result_sha256":digest(["nominal"]*20+["outlier-1","outlier-2"]),
                      "allowed_status":"complete"},
            good_work={"request_id":"BATCH-A22","source_count":22,
                       "status":"complete","result_sha256":digest(["nominal"]*20+["outlier-1","outlier-2"])},
            bad_work={"request_id":"BATCH-A22","source_count":22,
                      "status":"complete","result_sha256":digest(["nominal"]*22)}),
        Task(
            task_id="api-research-02",family="api_service",price=70,
            specification="Research API must deliver the exact requested report ID with the agreed digest, not just a successful HTTP response.",
            evidence={"request_id":"REPORT-609","expected_source_count":14,
                      "result_sha256":digest("independent validated report 609"),
                      "allowed_status":"complete"},
            good_work={"request_id":"REPORT-609","source_count":14,"status":"complete",
                       "result_sha256":digest("independent validated report 609")},
            bad_work={"request_id":"REPORT-609","source_count":14,"status":"complete",
                      "result_sha256":digest("different report with same metadata")}),
    ])
    # Task calibration, inspired by SWE-bench Verified: no impossible or mislabelled jobs.
    for task in jobs:
        yes, _ = evaluate(task, task.good_work)
        no, _ = evaluate(task, task.bad_work)
        if not yes or no:
            raise ProtocolViolation(f"task {task.task_id} failed fixture feasibility audit")
    return jobs
