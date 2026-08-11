"""M1 — root-cause probe for mistral-small-3.1 on OpenRouter (Cloudflare, its only provider).

SYMPTOM: finish_reason='error' under HTTP 200, prompt_tokens=0, completion_tokens=1, and a cut-off
echo of the question. Reproducible 2/2. Excluding the provider 404s because no other serves it.

This TROUBLESHOOTS rather than retests: it varies one dimension at a time to find which request
property triggers the failure, or to establish that the endpoint fails unconditionally.

A failed variant is DATA here, so failures are recorded — but each is recorded with its own explicit
outcome label and exception type, never as a neutral value that could be mistaken for a clean result
(the D-OR-5 rule). `ok` is a tri-state: True / False / None-never-used.
"""
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, "/home/ra/Projects/claude/skills/llm-api")
import llm_api  # noqa: E402

# The model under investigation is an ARGUMENT, not a constant. This script was written for one
# endpoint's failure (M1) but the probe matrix -- vary max_tokens, temperature, message shape,
# streaming, role, prompt length -- is what you want for ANY provider returning finish_reason=error.
# Pass --model; there is deliberately no default, so a run always records which endpoint it probed.
MODEL = None
URL = "https://openrouter.ai/api/v1/chat/completions"
FX = json.load(open(os.path.join(HERE, "runs", "fx_smoke4.json")))[0]["prompt"]
PLAIN = ("Will the share of global silver production disrupted by violence in Mexico exceed 1.0% "
         "on April 1, 2026? Answer Yes or No.")


def variants():
    """One dimension varied per row, against a common baseline."""
    return [
        ("baseline", {"messages": [{"role": "user", "content": FX}],
                      "max_tokens": 4000, "temperature": 0.0}),
        ("tiny_prompt", {"messages": [{"role": "user", "content": "Reply with the single word OK."}],
                         "max_tokens": 4000, "temperature": 0.0}),
        ("no_latex", {"messages": [{"role": "user", "content": PLAIN}],
                      "max_tokens": 4000, "temperature": 0.0}),
        ("small_budget", {"messages": [{"role": "user", "content": FX}],
                          "max_tokens": 256, "temperature": 0.0}),
        ("no_temperature", {"messages": [{"role": "user", "content": FX}], "max_tokens": 4000}),
        ("system_split", {"messages": [{"role": "system", "content": "You predict future events."},
                                       {"role": "user", "content": PLAIN}],
                          "max_tokens": 4000, "temperature": 0.0}),
        ("temp_0p7", {"messages": [{"role": "user", "content": FX}],
                      "max_tokens": 4000, "temperature": 0.7}),
        ("huge_budget", {"messages": [{"role": "user", "content": FX}],
                         "max_tokens": 32000, "temperature": 0.0}),
    ]


def call(payload):
    body = dict(payload, model=MODEL)
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {llm_api.load_key('OPENROUTER_API_KEY')}"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r)


def main():
    global MODEL
    import argparse
    ap = argparse.ArgumentParser(description="Probe one endpoint's request-shape failures.")
    ap.add_argument("--model", required=True,
                    help="the model id to probe, e.g. the one returning finish_reason=error")
    MODEL = ap.parse_args().model
    rows, spend = [], 0.0
    for name, payload in variants():
        for rep in (1, 2):
            row = {"variant": name, "rep": rep,
                   "max_tokens": payload.get("max_tokens"),
                   "temperature": payload.get("temperature", "<omitted>"),
                   "n_messages": len(payload["messages"]),
                   "prompt_chars": sum(len(m["content"]) for m in payload["messages"])}
            try:
                d = call(payload)
                ch = (d.get("choices") or [{}])[0]
                u = d.get("usage") or {}
                txt = ((ch.get("message") or {}).get("content")) or ""
                spend += u.get("cost", 0) or 0
                row.update({"outcome": "REPLY", "provider": d.get("provider"),
                            "finish_reason": ch.get("finish_reason"),
                            "native_finish_reason": ch.get("native_finish_reason"),
                            "prompt_tokens": u.get("prompt_tokens"),
                            "completion_tokens": u.get("completion_tokens"),
                            "chars": len(txt), "tail": txt[-90:],
                            "healthy": ch.get("finish_reason") != "error" and bool(u.get("prompt_tokens"))})
            except Exception as e:
                # An exception is its OWN labelled outcome, with its type -- never a neutral value.
                row.update({"outcome": "EXCEPTION", "error_type": type(e).__name__,
                            "detail": str(e)[:300], "healthy": False})
            rows.append(row)
            print(f"    {name:<16} rep{rep}  {row.get('outcome'):<9} "
                  f"finish={str(row.get('finish_reason')):<8} "
                  f"ptok={str(row.get('prompt_tokens')):<6} ctok={str(row.get('completion_tokens')):<6} "
                  f"chars={str(row.get('chars')):<6} healthy={row.get('healthy')}", flush=True)
            time.sleep(1)
    out = os.path.join(HERE, "..", "..", "..", "plans", "openrouter-output-integrity",
                       "verification", "M1")
    os.makedirs(out, exist_ok=True)
    json.dump({"model": MODEL, "rows": rows, "reported_spend": spend},
              open(os.path.join(out, "matrix.json"), "w"), indent=1)
    healthy = [r for r in rows if r.get("healthy")]
    print(f"\n  {len(rows)} probes, {len(healthy)} healthy, reported spend ${spend:.6f}")
    if healthy:
        print(f"  A WORKING VARIANT EXISTS: {sorted({r['variant'] for r in healthy})}")
    else:
        print(f"  NO variant succeeded — the endpoint fails unconditionally across "
              f"{len({r['variant'] for r in rows})} request shapes; exclusion is justified.")
    print(f"  matrix -> {os.path.normpath(os.path.join(out, 'matrix.json'))}")


if __name__ == "__main__":
    main()
