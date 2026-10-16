"""Read-only forensic summary of prior live ERC-8183 Inspect model settings.

This checks historical request settings, not whether a provider delivered a
particular depth of hidden reasoning. It never calls a model or writes a ledger.
"""

from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path

from inspect_ai.log import read_eval_log

from agent_economic_trust.reporting import _agent_for_event


STUDIES = ("ERC8183_PARTIAL_CLAIM014", "ERC8183_PRESSURE016")


def summarize(root: Path) -> dict:
    result = {"schema": "bilateral030-prior-live-config-forensic-v1",
              "source": "saved Inspect .eval ModelEvent.config/usage",
              "scope": "all eight archived PARTIAL014/PRESSURE016 episode logs",
              "studies": {}}
    for study in STUDIES:
        paths = sorted((root / "artifacts/gates" / study / "runs-001" /
                        "episodes").glob("*/inspect.eval"))
        if len(paths) != (5 if study.endswith("014") else 3):
            raise ValueError(study + " saved archive count differs")
        totals = defaultdict(lambda: {"model_events": 0,
                                     "reported_reasoning_token_events": 0,
                                     "reported_reasoning_tokens": 0})
        episodes = []
        for path in paths:
            log = read_eval_log(path, resolve_attachments=True)
            if len(log.samples or []) != 1:
                raise ValueError("expected one sample in " + str(path))
            sample = log.samples[0]
            events = []
            for event in sample.events:
                if event.event != "model":
                    continue
                role = _agent_for_event(event, sample)
                if role not in {"provider", "auditor"}:
                    raise ValueError("missing role span in " + str(path))
                config = event.config
                actual = (config.reasoning_effort, config.reasoning_history,
                          config.max_tokens, config.max_retries)
                if actual != ("high", "none", 4096, 0):
                    raise ValueError("historical model config differs in " + str(path))
                usage = getattr(event.output, "usage", None)
                tokens = getattr(usage, "reasoning_tokens", None)
                if tokens is not None and (type(tokens) is not int or tokens < 0):
                    raise ValueError("invalid reported reasoning usage in " + str(path))
                totals[role]["model_events"] += 1
                totals[role]["reported_reasoning_token_events"] += (
                    tokens is not None)
                totals[role]["reported_reasoning_tokens"] += tokens or 0
                events.append({"role": role, "model_event_route": event.model,
                               "reasoning_effort_requested": config.reasoning_effort,
                               "reasoning_history": config.reasoning_history,
                               "max_output_tokens_requested": config.max_tokens,
                               "max_retries": config.max_retries,
                               "reasoning_tokens_reported": tokens})
            episodes.append({"episode_id": sample.id,
                             "archive": str(path.relative_to(root)),
                             "archive_sha256": sha256(path.read_bytes()).hexdigest(),
                             "inspect_status": log.status,
                             "sample_error": bool(sample.error),
                             "model_events": events})
        result["studies"][study] = {
            "episode_count": len(paths),
            "role_totals": dict(totals),
            "episodes": episodes,
        }
    result["interpretation"] = (
        "Historical live Sol and Sonnet calls requested high reasoning in both "
        "roles. Reported reasoning-token counts do not prove a particular "
        "amount of private deliberation or explain every decision. The new "
        "BILATERAL030 mock adapter initially omitted the auditor per-agent "
        "setting; that new source gap is separate from these older runs.")
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path,
                        default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    print(json.dumps(summarize(args.root.resolve()), indent=2, sort_keys=True))
