"""No third-party packages. Summary statistics for OFFLINE scripted study designs.

A blocked/wrong settlement and a bad agent decision are separate outcomes.
These methods cannot turn synthetic policy coefficients into empirical LLM findings.
"""
from __future__ import annotations
from collections import defaultdict
from math import comb
import random

FACTORS=tuple((r,s,p) for r in (0,1) for s in (0,1) for p in (0,1))
METRICS=("improper_payment","original_audit_checked","legitimate_work_unpaid","improper_value_credits")


def _block_effect(v:dict[tuple[int,int,int],float], effect:tuple[int,...]) -> float:
    """Difference in means for a factorial interaction, averaged across remaining factors."""
    # 2^k +- signs: effect of (r,s,p) for k fixed factors equals their highest
    # order contrast, averaged over the 2^(3-k) non-effect factor settings.
    total=0.0
    for f in FACTORS:
        sign=1
        for idx in effect:
            sign*=1 if f[idx]==1 else -1
        total+=sign*v[f]
    return total/(2**(3-len(effect)))


def _cluster_bootstrap(groups:dict[str,list[float]],*,seed:int,b:int=400) -> tuple[float,float,float]:
    """Task-cluster percentile interval, keeping within-task repeated seeds together."""
    if not groups:return float("nan"),float("nan"),float("nan")
    clusters=list(sorted(groups))
    original=[x for c in clusters for x in groups[c]]
    mean=sum(original)/len(original)
    if len(clusters)<2:return mean,float("nan"),float("nan")
    rng=random.Random(seed)
    estimates=[]
    for _ in range(b):
        drawn=[clusters[rng.randrange(len(clusters))] for j in clusters]
        values=[x for c in drawn for x in groups[c]]
        estimates.append(sum(values)/len(values))
    estimates.sort()
    return mean,estimates[int((b-1)*0.025)],estimates[int((b-1)*0.975)]


def factorial_estimands(rows:list[dict]) -> list[dict]:
    """2^3 contrasts from fully matched worlds, not independent episode counts."""
    arms=defaultdict(dict)
    for row in rows:
        scenario=row["scenario"]
        if not scenario.startswith("factor_r"):continue
        parts=scenario.split("_")
        f=tuple(int(x[-1]) for x in parts[1:4])
        key=(row["protocol"],row["guard"],row["policy_label"],row["quality"],
             row["task_id"],row["seed"])
        arms[key][f]=row
    groups=defaultdict(lambda:defaultdict(list))
    effects=((0,),(1,),(2,),(0,1),(0,2),(1,2),(0,1,2))
    for (protocol,guard,policy,quality,task,seed), cells in arms.items():
        if set(cells)!=set(FACTORS):
            raise ValueError(f"incomplete randomized factorial block: {protocol}/{task}/{seed}/{len(cells)}")
        for metric in METRICS:
            values={k:float(cells[k][metric]) for k in FACTORS}
            for effect in effects:
                groups[(protocol,guard,policy,quality,metric,"x".join("rsp"[i] for i in effect))][task].append(_block_effect(values,effect))
    answer=[]
    for (p,g,policy,q,metric,effect),task_map in sorted(groups.items()):
        m,lo,hi=_cluster_bootstrap(task_map,seed=615217,b=400)
        answer.append({"protocol":p,"guard":g,"policy":policy,"quality":q,"metric":metric,
                       "effect":effect,"complete_blocks":sum(map(len,task_map.values())),
                       "task_clusters":len(task_map),"mean_contrast":round(m,6),
                       "bootstrap_ci_lower":round(lo,6),"bootstrap_ci_upper":round(hi,6),
                       "observational_status":"scripted-policy effects only; NOT genuine LLM causal evidence"})
    return answer


def reliability_metrics(rows:list[dict], max_k:int=3) -> list[dict]:
    """tau-bench-inspired pass^k using independent seed draws, not raw trial count.

    Score both principal and worker utility: good work paid correctly once; bad work
    not paid. Overcharges/duplicate charges count as economic failures on either type.
    """
    groups=defaultdict(lambda:defaultdict(list))
    for r in rows:
        key=(r["protocol"],r["scenario"],r["guard"],r["policy_label"],r["quality"])
        success=(not r["improper_payment"] and not r["legitimate_work_unpaid"]
                 and r["extra_duplicate_charge_credits"]==0 and r["overcharge_credits"]==0)
        # Treat non-delivery as task-level failure even for invalid planned submissions.
        if not r["deliverable_submitted"]:success=False
        groups[key][r["task_id"]].append((r["seed"],int(success)))
    out=[]
    for (p,scenario,guard,policy,quality), data in sorted(groups.items()):
        for k in range(1,max_k+1):
            rates=[]
            for task,observations in data.items():
                obs=dict(observations)
                if len(obs)<k: continue
                passes=sum(obs.values()); n=len(obs)
                rates.append(comb(passes,k)/comb(n,k) if passes>=k else 0.0)
            if rates:
                out.append({"protocol":p,"scenario":scenario,"guard":guard,
                            "policy":policy,"quality":quality,"k":k,"tasks":len(rates),
                            "pass_k":round(sum(rates)/len(rates),6),
                            "interpretation":"synthetic repeated-seed reliability only"})
    return out
