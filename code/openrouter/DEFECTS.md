# Open defects — phase-2 OpenRouter harness

Filed against `plans/openrouter-output-integrity`. Published so the partial data is read with
its known problems attached, rather than as a clean result.

**5 open.**

## D-OR-4

max_tokens is not honoured as a BILLING cap by 5 providers (deepseek, minimax, moonshotai, qwen, z-ai): worst observed 98,349 completion tokens billed against a 4,000 cap (24.6x). MEASURED AT --max-tokens 4000. RE-MEASURED 2026-08-10 at the current default of 64,000 over the 872 fxgate records that carry a budget and usage: ZERO of 37 models exceeded the budget asked for; the closest was gemini-3.5-flash at 0.96 of 64,000, and that model is not in the current roster. This does NOT disprove the defect -- at 64,000 almost nothing approaches the cap, so the run no longer EXERCISES whether the cap is honoured. The behaviour is unexercised, not fixed. What actually bounds cost is spend.Ledger against --max-spend: a hard cumulative ceiling checked under lock before each charge, journaled per attempt, idempotent on resume -- so the exposure is one in-flight call, not an unbounded bill. max_tokens is a SHAPE control here, not a cost control, and the plan should not claim otherwise.

- **regression test:** not yet written
- **fix:** not yet fixed

## D-OR-24

QUARANTINE FIRES ON A MODEL THAT IS WORKING. BUDGET_CAPPED is in CR.METHOD_DEFECT, so it counts toward --quarantine-after. But BUDGET_CAPPED now means 'truncated at the model's OWN published ceiling with nowhere to escalate' -- since M6-T22 we ask for exactly max_completion_tokens, so a cap is the model wanting to write more than the vendor allows, not a budget WE chose too small. There is no method to fix and no remedy in stopping. Live on the 2026-08-10 FutureX run: nvidia/nemotron-3-super-120b-a12b answered cleanly 65 of 82 (79%), hit 8 BUDGET_CAPPED (ceiling 16,384 against a 1,000,000 context), and was quarantined -- censoring its remaining 33 of 110 units. That is model-correlated coverage loss on a model that mostly works, which A13 is designed to fail. The other METHOD_DEFECT verdicts (EMPTY_HTTP, SCHEMA_ERROR, PROVIDER_ERROR) are things we can fix or the provider can; this one is a property of the model and the question.

- **regression test:** a model whose only non-clean verdicts are BUDGET_CAPPED at its own published ceiling must NOT be quarantined; a model with the same count of genuine method defects still must be
- **fix:** not started -- either drop BUDGET_CAPPED from the quarantine trigger, or count it only when the requested budget was BELOW the model's ceiling (i.e. when we actually chose it). The verdict itself stays: an unfinished answer is never scored as a wrong one.

## D-OR-26

I OVERRULED A CODEX FINDING ON A FALSE FACT, AND WROTE THE FALSE FACT INTO THE DESIGN. subtasks/23 states 'The failure domain is the MODEL -- we cannot pause a provider' and argues 'a pause the provider rule would be unimplementable: we cannot route away from Nebius'. THAT IS WRONG. OpenRouter documents per-request provider control: provider.ignore (skip named provider slugs), provider.only (allow only named slugs), provider.order, provider.allow_fallbacks, provider.sort, provider.max_price. A specific serving provider CAN be excluded per call. Codex's C1/C15 remedy (pause the failure domain, provider OR model) was implementable as written, and the owner had ruled 'use codex's policy'; I then narrowed that ruling to model-only on a fact I never checked. Source of the error: I inferred the mechanism from our own run records (gemma-3-27b seen served by Nebius, Parasail and Phala) and from our per_provider cap keying on the vendor prefix, instead of reading the vendor's documentation. WHAT IS STILL TRUE: OpenRouter's default routing deprioritises recently-failed providers and 502 is documented as silently retried against a different provider endpoint when fallback routing is on -- so retry-as-diversification is real, and is now a CITED fact rather than my inference. WHAT IS NOT ESTABLISHED: whether per-provider pausing is WORTH building here. That is a design question for the owner and Codex, not a capability question, and it must not be re-answered by another unchecked assertion.

- **regression test:** PENDING -- a test asserting the documented provider fields are reachable from our client, plus a check that no design document claims provider routing is impossible.
- **fix:** PENDING -- subtasks/23 and log.md swept 2026-08-10 to retract the claim; the design decision (build per-provider pausing or not) is REOPENED and belongs to the owner + a fresh Codex round.

## D-OR-27

EVERY 403 HALTS THE ENTIRE RUN, BUT NOT EVERY 403 IS THE ACCOUNT'S. classify_fault maps ACCOUNT_FATAL_STATUS = {401, 402, 403} straight to TERMINAL_ACCOUNT, which stops all models. OpenRouter documents 403 as 'Forbidden (insufficient permissions, guardrail block, or moderation flag)' and returns metadata.reasons for a moderation block. So ONE moderation-flagged item on ONE model would halt a 2,500-unit paid run and report it as an account fault. This is the MIRROR of D-OR-16: that defect blamed a model for the account's fault; this one blames the account for a single request's fault. The discriminator D-OR-16 established -- 'would this error have hit any model I called?' -- is exactly what distinguishes them, and metadata.reasons is the field that answers it. NOT OBSERVED IN A RUN: both live 403s were genuine org-budget faults, so this is a read of the code against the documentation, not a reproduced failure.

- **regression test:** PENDING -- a stubbed 403 carrying metadata.reasons must pause its unit or model, NOT halt the run; a 403 with budget wording must still halt. Both in test_infra_faults.py.
- **fix:** PENDING

## D-OR-28

THE CLASSIFIER REGEX-MATCHES ENGLISH PROSE FOR A DISTINCTION THE VENDOR PUBLISHES AS A TYPED FIELD. _EXHAUSTED = re.compile(r'budget|quota|credit|insufficient|spend|billing|payment|exceeded') is run over the error message to decide whether a 429 is momentary throttling or a spent allowance -- a control-flow decision made by pattern-matching a human-readable sentence, which a vendor wording change silently reclassifies. OpenRouter documents that it 'normalizes every upstream provider error into the stable, typed error_type vocabulary', exposed at error.metadata.error_type and explicitly distinct from native provider codes. We do read an error_type attribute, but it is whatever llm_api happened to set, not the documented metadata field, and the prose regex overrides it. Also 408 ('Your request timed out', documented retryable) is in no status set and only reaches TRANSIENT via the unclassified fallback -- right behaviour by accident, not by design.

- **regression test:** PENDING -- assert the documented error_type is read from error.metadata.error_type and takes precedence over any prose match; assert 408 is classified TRANSIENT by an explicit rule.
- **fix:** PENDING

---

Three of these (D-OR-26/27/28) were found by reading OpenRouter's own documentation after the
harness was built. All 454 tests were green at the time: they encoded the author's assumptions,
not the vendor's published contract. That is the cautionary note worth carrying away.
