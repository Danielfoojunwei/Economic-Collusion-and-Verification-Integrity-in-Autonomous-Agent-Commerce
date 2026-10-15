"""Offline benchmark CLI.  No wallets, chain RPC, or vendor payment APIs."""
from __future__ import annotations
import argparse
import sys
from collections import defaultdict
import csv
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import platform
from . import __version__
from .model import canonical, digest, ProtocolViolation
from .protocols import PROTOCOLS, ROADMAP
from .runtime import SCENARIOS, make_condition, run_trial
from .tasks import make_tasks
from .market import run_market
from .wiremock import SandboxHTTP,smoke_once


def comma_list(text, universe):
    if text == "all":
        return list(universe)
    values=[s.strip() for s in text.split(",") if s.strip()]
    unknown=set(values)-set(universe)
    if unknown:
        raise ProtocolViolation("unknown entries: "+", ".join(sorted(unknown)))
    return values


def report(rows: list[dict], out: Path):
    bucket=defaultdict(list)
    for r in rows:
        bucket[(r["protocol"],r["policy"],r["guard"],r["scenario"])].append(r)
    summary=[]
    for k,values in sorted(bucket.items()):
        attempted=[v for v in values if v["work_submitted"]]
        invalid=[v for v in attempted if not v["actual_conforming"]]
        valid=[v for v in attempted if v["actual_conforming"]]
        summary.append(dict(zip(("protocol","policy","guard","scenario"),k)) | {
            "trials":len(values), "delivered":len(attempted),
            "invalid_delivered":len(invalid),"valid_delivered":len(valid),
            "bad_work_paid":sum(v["wrong_payment"] for v in attempted),
            "bad_work_pay_rate":round(sum(v["wrong_payment"] for v in invalid)/len(invalid),4) if invalid else "NA",
            "good_work_unpaid":sum(v["good_work_unpaid"] for v in valid),
            "good_work_nonpay_rate":round(sum(v["good_work_unpaid"] for v in valid)/len(valid),4) if valid else "NA",
            "checks":sum(v["checks"] for v in attempted),
            "verification_effort_credits":sum(v["auditor_budget_consumed"] for v in attempted),
            "blocked":sum(v["blocked"] for v in values),
            "simulated_side_payments":sum(v["side_payment"] for v in values),
        })
    if summary:
        with (out/"summary.csv").open("w",newline="",encoding="utf-8") as f:
            writer=csv.DictWriter(f,fieldnames=list(summary[0]))
            writer.writeheader()
            writer.writerows(summary)
    # Matched, descriptive contrasts only; null model not validated as LLM behaviour.
    keyed={(r["protocol"],r["task_id"],r["policy"],r["guard"],
            r["quality"],r["condition"]["episode"],r["seed"]):r for r in rows if r["scenario"]=="baseline"}
    contrasts=defaultdict(list)
    for r in rows:
        if r["scenario"]=="baseline": continue
        key=(r["protocol"],r["task_id"],r["policy"],r["guard"],
             r["quality"],r["condition"]["episode"],r["seed"])
        ref=keyed.get(key)
        if not ref or not r["work_submitted"] or not ref["work_submitted"]: continue
        group=(r["protocol"],r["policy"],r["guard"],r["scenario"],r["quality"])
        contrasts[group].append((int(r["wrong_payment"])-int(ref["wrong_payment"]),
                                 int(r["checks"])-int(ref["checks"])))
    contrast_rows=[]
    for k,values in sorted(contrasts.items()):
        contrast_rows.append(dict(zip(("protocol","policy","guard","scenario","quality"),k)) | {
            "matched_units":len(values),
            "delta_bad_payment_rate":round(sum(v[0] for v in values)/len(values),4),
            "delta_checks_per_trial":round(sum(v[1] for v in values)/len(values),4)})
    if contrast_rows:
        with (out/"matched_contrasts.csv").open("w",newline="",encoding="utf-8") as f:
            writer=csv.DictWriter(f,fieldnames=list(contrast_rows[0]))
            writer.writeheader()
            writer.writerows(contrast_rows)
    markdown=["# Offline pilot report", "", "**SIMULATOR OUTPUT — NOT REAL AGENT OBSERVATIONS, STANDARD CONFORMANCE, OR PROTOCOL VULNERABILITY EVIDENCE.**", "",
              f"Total trials: **{len(rows)}** across {len(set(r['protocol'] for r in rows))} protocol-shaped adapters.",
              "", "The `economic` policy has synthetic, hand-selected probabilities; its results have no empirical interpretation as LLM susceptibility.",
              "All amounts are fictional credits. `objective_recheck` is an added idealised objective oracle, not a native payment-protocol property.",
              "", "## Aggregated descriptive rates by payment family", "",
              "| Protocol | Policy | Guard | Scenario | Wrong payments / invalid delivered | Legitimate nonpayments / valid delivered |",
              "|---|---|---|---|---|---|"]
    for row in summary:
        if row["scenario"] in ("baseline","mixed_pressure"):
            markdown.append(f"| {row['protocol']} | {row['policy']} | {row['guard']} | {row['scenario']} | {row['bad_work_paid']}/{row['invalid_delivered']} | {row['good_work_unpaid']}/{row['valid_delivered']} |")
    markdown += ["", "Invalid work payment rates for checkout and charge protocols are largely a consequence of intentionally omitting independently enforced service-quality conditions in this modeled configuration, not evidence of a specification violation.",
                 "", "## Reproduction", "", "`python -m unittest discover -s tests -v`", "",
                 "See `trials.jsonl`, `summary.csv`, `matched_contrasts.csv`, and `manifest.json` for complete inputs and events."]
    (out/"report.md").write_text("\n".join(markdown)+"\n",encoding="utf-8")
    return summary


def cmd_run(args):
    protocols=comma_list(args.protocols,PROTOCOLS)
    scenarios=comma_list(args.scenarios,SCENARIOS)
    policies=comma_list(args.policies,("truthful","budget_sensitive","economic","captured","llm_local"))
    guards=comma_list(args.guards,("none","objective_recheck"))
    qualities=comma_list(args.qualities,("good","bad"))
    if "llm_local" in policies and not (args.model and args.endpoint):
        raise ProtocolViolation("--model and --endpoint are mandatory with llm_local")
    if args.episodes<1 or args.seeds<1:
        raise ProtocolViolation("episodes and seeds must be positive")
    total = (len(protocols)*len(scenarios)*len(policies)*len(guards)*len(qualities)*
             args.seeds*args.episodes*(len(make_tasks()) if args.tasks=="all" else len(args.tasks.split(","))))
    if total > args.max_trials:
        raise ProtocolViolation(f"{total} trials exceed --max-trials {args.max_trials}; request a smaller batch or explicitly raise limit")
    tasks=make_tasks()
    if args.tasks!="all":
        allowed=comma_list(args.tasks,[t.task_id for t in tasks])
        tasks=[t for t in tasks if t.task_id in allowed]
    out=Path(args.out)
    out.mkdir(parents=True,exist_ok=True)
    rows=[]
    with (out/"trials.jsonl").open("w",encoding="utf-8") as f:
        for protocol in protocols:
            for task in tasks:
                for scenario in scenarios:
                    for policy in policies:
                        for guard in guards:
                            for quality in qualities:
                                for seed in range(1,args.seeds+1):
                                    condition=make_condition(scenario,quality)
                                    carry=[condition.budget]*condition.committee_size
                                    for episode in range(1,args.episodes+1):
                                        condition=make_condition(scenario,quality,episode)
                                        tr=run_trial(protocol,task,condition,policy,guard,seed,
                                                     balances=carry if args.episodes>1 else None,
                                                     model=args.model,endpoint=args.endpoint)
                                        d=asdict(tr) | {"seed":seed}
                                        f.write(canonical(d)+"\n")
                                        rows.append(d)
    report(rows,out)
    manifest={"harness":"PaidAuditBench","version":__version__,"execution":"NO-FUNDS, OFFLINE",
              "created_utc":datetime.now(timezone.utc).isoformat(),
              "python":platform.python_version(),"protocols":protocols,"scenarios":scenarios,
              "policies":policies,"guards":guards,"task_count":len(tasks),"episode_count":args.episodes,
              "repetitions":args.seeds,"trials":len(rows),
              "provenance_note":"All simulated scores require empirical validation with real agent models and real protocol SDKs.",
              "official_protocol_sources":{k:PROTOCOLS[k].source for k in protocols},
              "artifact_sha256":{name:sha256((out/name).read_bytes()).hexdigest()
                                  for name in ("trials.jsonl","summary.csv","matched_contrasts.csv","report.md") if (out/name).exists()}}
    (out/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8")
    print(f"Wrote {len(rows)} OFFLINE SIMULATION trials to {out.resolve()}")
    print(f"Inspect: {out/'report.md'}, {out/'summary.csv'}, {out/'trials.jsonl'}")


def cmd_market(args):
    out=Path(args.out)
    out.mkdir(parents=True,exist_ok=True)
    rows=[]
    graph={}
    for protocol in comma_list(args.protocols,PROTOCOLS):
        for pattern in comma_list(args.patterns,("reciprocal","repeated","ring3","rotating")):
            for seed in range(1,args.seeds+1):
                batch,g=run_market(protocol,args.policy,pattern,args.episodes,seed,args.guard)
                rows.extend(batch)
                graph[f"{protocol}|{pattern}|seed{seed}"]=g
    with (out/"trials.jsonl").open("w",encoding="utf-8") as f:
        for r in rows: f.write(canonical(r)+"\n")
    (out/"economic_graphs.json").write_text(json.dumps(graph,indent=2)+"\n")
    report(rows,out)
    (out/"manifest.json").write_text(json.dumps({
        "harness":"PaidAuditBench market simulator", "version":__version__,
        "execution":"NO-FUNDS OFFLINE SCRIPTED POLICY", "created_utc":datetime.now(timezone.utc).isoformat(),
        "episodes_per_pattern":args.episodes,"seeds":args.seeds,"trials":len(rows),
        "policy":args.policy,"patterns":args.patterns,"protocols":args.protocols,
        "artifact_sha256": {name:sha256((out/name).read_bytes()).hexdigest() for name in
           ("trials.jsonl","summary.csv","economic_graphs.json")},
        "warning":"These generated relationships do not demonstrate emergent LLM collusion."
    },indent=2)+"\n")
    print(f"Wrote {len(rows)} market episodes (scripted policies; mock payments): {out.resolve()}")


def cmd_wire(args):
    with SandboxHTTP() as srv:
        outcomes=[smoke_once(srv,p,attack=a) for p in ("x402","mpp")
                  for a in ("none","alter_amount")]
    for result in outcomes:
        print(f"{result['protocol']}: attack={result['attack']} -> "
              f"402/{result['credential_status']} replay={result['replay_status']}")
    if any(x["credential_status"] != (200 if x["attack"]=="none" else 403) for x in outcomes):
        raise ProtocolViolation("wiremock smoke failed")
    print("PASS: loopback HTTP 402 wire-shape exercises. No scheme-valid cryptography, no money.")


def cmd_inspect(args):
    trials=Path(args.file)
    n=0; failures=[]
    with trials.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip(): continue
            r=json.loads(line)
            expected=digest({"trial":r["trial_id"],"events":r["trace"]})
            if expected!=r["trace_hash"]:
                failures.append(r["trial_id"])
            n+=1
    if failures:
        raise ProtocolViolation(f"{len(failures)}/{n} local trace hashes failed, first: {failures[0]}")
    print(f"PASS: {n} local trace integrity digests verified. Not cryptographic signatures.")


def cmd_list(args):
    print("PROTOCOL-SHAPED LOCAL ADAPTERS (none perform real payments):")
    for p in PROTOCOLS.values():
        print(f"  {p.name:21} {p.kind:22} stage={p.payment_stage} | {p.note}")
    print("\nSCENARIOS:", ", ".join(SCENARIOS))
    print("\nOUT-OF-SCOPE REAL INTEGRATIONS:")
    for x in ROADMAP:
        print(" ", x["status"],x["name"], "—",x["reason"])


def main(argv=None):
    parser=argparse.ArgumentParser(prog="paidaudit",description="No-funds economic verification protocol simulator")
    sub=parser.add_subparsers(dest="cmd",required=True)
    sub.add_parser("list",help="print available models and coverage")
    r=sub.add_parser("run",help="run complete offline factorial experiment and export evidence")
    r.add_argument("--config",default="",help="optional JSON file; CLI flags take precedence")
    r.add_argument("--max-trials",type=int,default=100000)
    r.add_argument("--out",default="runs/pilot")
    r.add_argument("--protocols",default="all")
    r.add_argument("--scenarios",default="all")
    r.add_argument("--policies",default="truthful,economic")
    r.add_argument("--guards",default="none,objective_recheck")
    r.add_argument("--qualities",default="good,bad")
    r.add_argument("--tasks",default="all")
    r.add_argument("--episodes",type=int,default=1,help=">1 carries verifier budget across episodes; no model learning")
    r.add_argument("--seeds",type=int,default=2)
    r.add_argument("--model",default="",help="local model name for llm_local")
    r.add_argument("--endpoint",default="",help="loopback OpenAI-compatible /chat/completions endpoint")
    m=sub.add_parser("market-run",help="repeated provider-auditor network and financial edge simulator")
    m.add_argument("--out",default="runs/market")
    m.add_argument("--protocols",default="erc8183_draft")
    m.add_argument("--patterns",default="reciprocal,rotating,ring3")
    m.add_argument("--policy",default="economic",choices=("truthful","economic","budget_sensitive","captured"))
    m.add_argument("--guard",default="none",choices=("none","objective_recheck"))
    m.add_argument("--episodes",type=int,default=12)
    m.add_argument("--seeds",type=int,default=2)
    x=sub.add_parser("realism-run",help="run research-driven matched-world paid-service study (NO FUNDS)")
    x.add_argument("--config",default="configs/realism_pilot.json")
    x.add_argument("--out",default="runs/realism_pilot")
    x.add_argument("--model",default="")
    x.add_argument("--endpoint",default="")
    sub.add_parser("wire-smoke",help="real loopback HTTP 402 header flow, mock credentials only")
    a=sub.add_parser("verify-log",help="recompute trial event SHA-256 digests")
    a.add_argument("file")
    orig_args=list(sys.argv[1:] if argv is None else argv)
    args=parser.parse_args(orig_args)
    if args.cmd == "run" and args.config:
        config=json.loads(Path(args.config).read_text(encoding="utf-8"))
        explicitly_set={arg.split("=",1)[0] for arg in orig_args if arg.startswith("--")}
        recognized={"protocols","scenarios","policies","guards","qualities","tasks","seeds","episodes","out"}
        for k,v in config.items():
            name="out" if k=="output" else k
            if name in recognized and "--"+name.replace("_","-") not in explicitly_set:
                setattr(args,name,v)
    try:
        if args.cmd=="realism-run":
            from .study import run_study
            result=run_study(json.loads(Path(args.config).read_text(encoding="utf-8")),
                             Path(args.out),model=args.model,endpoint=args.endpoint)
            print(f"Created {result['trial_count']} MATCHED LOCAL SIMULATION worlds at {Path(args.out).resolve()}")
            return
        {"list":cmd_list,"run":cmd_run,"market-run":cmd_market,"wire-smoke":cmd_wire,"verify-log":cmd_inspect}[args.cmd](args)
    except (ProtocolViolation, OSError, ValueError) as e:
        parser.error(str(e))

if __name__=="__main__":
    main()
