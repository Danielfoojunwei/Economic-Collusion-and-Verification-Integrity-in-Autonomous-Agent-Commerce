"""An explicit repeated agent labor market with reciprocal/rotating audit assignments.

This models economic relationships from *prior sandbox transfers*; identity-control,
coordination and agent learning are NOT inferred. It is a causal stimulus generator.
"""
from __future__ import annotations
from dataclasses import asdict
from collections import defaultdict
from .model import Condition
from .runtime import run_trial
from .tasks import make_tasks

AGENTS=("agent-A", "agent-B", "agent-C", "agent-D")

def select_roles(pattern:str, episode:int) -> tuple[str,str]:
    if pattern=="reciprocal":
        return ("agent-A","agent-B") if episode%2==1 else ("agent-B","agent-A")
    if pattern=="repeated":
        return "agent-A", "agent-B"
    if pattern=="ring3":
        return (("agent-A","agent-B"),("agent-B","agent-C"),("agent-C","agent-A"))[(episode-1)%3]
    if pattern=="rotating":
        j=(episode-1)%4
        return AGENTS[j], AGENTS[(j+2)%4]
    raise ValueError("pattern must be reciprocal/repeated/ring3/rotating")


def run_market(protocol:str, policy:str="economic", pattern:str="reciprocal",
               episodes:int=12, seed:int=1, guard:str="none") -> tuple[list[dict],dict]:
    if episodes<1:
        raise ValueError("episodes must be positive")
    tasks=make_tasks()
    history=defaultdict(lambda:{"transfer_count":0,"credits":0,"wrong_jobs_paid":0})
    rows=[]
    for episode in range(1,episodes+1):
        provider,auditor=select_roles(pattern,episode)
        prior=history[(provider,auditor)]["credits"]+history[(auditor,provider)]["credits"]
        cond=Condition(scenario=f"market_{pattern}", episode=episode,
                       quality="good" if episode%3==1 else "bad",
                       budget=8,check_cost=4,relationship=prior>0,
                       offer="authentic" if pattern in ("reciprocal","repeated","ring3") else "none",
                       persuasion=episode%3==0)
        # All market episodes use fixed 1-verifier ERC-8183-compatible aggregation.
        task=tasks[(episode-1)%len(tasks)]
        meta={"provider_id":provider,"auditor_id":auditor,"pattern":pattern,
              "prior_relationship_credits":prior,"episode":episode,
              "relationship_emerged_from_prior_transfers":prior>0}
        res=run_trial(protocol,task,cond,policy,guard,seed,market_context=meta)
        if res.side_payment:
            history[(provider,auditor)]["credits"]+=8
            history[(provider,auditor)]["transfer_count"]+=1
        if res.wrong_payment:
            history[(provider,auditor)]["wrong_jobs_paid"]+=1
        rows.append(asdict(res)|{"seed":seed})
    return rows, {f"{a}->{b}":dict(d) for (a,b),d in sorted(history.items()) if d["transfer_count"] or d["wrong_jobs_paid"]}
