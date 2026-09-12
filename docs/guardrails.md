# Guardrails

This agent is handed a search engine and asked to look for a real person. That
creates two failure modes ordinary correctness testing doesn't cover:

1. **It looks for the wrong person** — a namesake, or someone the account
   holder wants to find but has no right to scan.
2. **It gets steered by what it reads** — search results are text written by
   strangers, some of whom would like to talk to an agent.

Everything below is an answer to one of those two. The dividing line the whole
design rests on:

> The model decides **what to search for** and **what a page appears to mean**.
> It never decides **who may be searched for**, **what counts as proof**, or
> **what gets stored**. Those live in code, because a prompt is a request, and
> a search result is attacker-controlled text.

Each rule says where it is enforced and what proves it. The distinction between
the two kinds of proof matters:

- **unit test** — the guard function rejects bad input.
- **eval case** — a model in the loop, given pages designed to make it try,
  cannot route around the guard. Stronger, and rarer: there are seven cases.

---

## 1. Who can be scanned

| Rule | Enforced | Proven by |
|---|---|---|
| No scan without a verified email or phone | [scans.py:49](../src/exposure_auditor/scans.py#L49) | `test_scan_requires_a_verified_identifier` |
| A proven username alone doesn't open the gate — it shows control of a profile, not of a contact point | [scans.py:49](../src/exposure_auditor/scans.py#L49) | `test_a_proven_username_alone_does_not_open_the_gate` |
| Usernames enter scope only after a code appears in a public bio | [scans.py:45](../src/exposure_auditor/scans.py#L45) | `test_unproven_usernames_are_left_out_of_scans`, `test_github_bio_proof`, `test_bluesky_bio_proof` |
| Attested names, usernames and photos are capped (3/5/5) | [config.py:82-84](../src/exposure_auditor/config.py#L82) | `test_names_must_be_attested_full_and_capped` |
| Every query must contain an in-scope identifier, verbatim | [scope.py:41](../src/exposure_auditor/agent/scope.py#L41) | `test_scope_guard_*`, and implicitly every eval case |
| `OR`, `\|` and `AROUND()` are rejected — `<me> OR <someone else>` would pass a contains-check | [scope.py:44](../src/exposure_auditor/agent/scope.py#L44) | `test_scope_guard_rejects_out_of_scope_queries` |
| Context details (city, workplace, birth year) are never search terms — only ever used to *rule out* | [scope.py:36](../src/exposure_auditor/agent/scope.py#L36) | `test_context_details_are_never_search_terms` |
| `site:` must be a bare domain | [scope.py:60](../src/exposure_auditor/agent/scope.py#L60) | `test_scope_guard_site_must_be_a_domain` |
| One tenant's data is never visible to another | API layer | `test_tenant_isolation`, `test_finding_verdicts_are_tenant_isolated` |

The gate is the reason this is an auditor and not a stalking tool. It is also
the weakest link — see [what isn't guarded](#what-isnt-guarded).

## 2. What may become a finding

| Rule | Enforced | Proven by |
|---|---|---|
| Only a `result_id` some tool actually returned this scan can be recorded | [orchestrator.py:346](../src/exposure_auditor/agent/orchestrator.py#L346) | eval metric `findings_outside_corpus: 0`; case 05 tells the agent to record a URL it never saw |
| Every claimed identifier must be visible in the URL, title or snippet the model was given | [orchestrator.py:372](../src/exposure_auditor/agent/orchestrator.py#L372) | `test_claimed_corroboration_must_be_visible` |
| A finding must rest on an identity (email, phone, username, photo, name) — a city identifies nobody | [orchestrator.py:359](../src/exposure_auditor/agent/orchestrator.py#L359) | `test_context_alone_does_not_identify_anyone` |
| A contradicting context detail with no strong identifier = namesake: counted, never stored | [orchestrator.py:383](../src/exposure_auditor/agent/orchestrator.py#L383) | `test_namesakes_are_counted_not_stored`; metric `namesake_leaks: 0`; cases 02, 03 |
| Only a strong identifier (email, phone, username, photo) makes a finding confident; a name, even with a matching city, waits for the account holder's verdict | [orchestrator.py:443](../src/exposure_auditor/agent/orchestrator.py#L443) | `test_name_only_results_wait_for_review`, `test_confirm_moves_a_name_only_result_into_the_plan`, eval cases 08 and 09 |
| Usernames and emails match on word boundaries — `plaine` is not `plaine88` | [matching.py:50](../src/exposure_auditor/agent/matching.py#L50) | `test_usernames_match_exactly_not_loosely`, `test_emails_match_whole_addresses_only`; case 07 |
| Names match across accents and URL slugs — `Meikäläinen` = `maija-meikalainen` | [matching.py:38](../src/exposure_auditor/agent/matching.py#L38) | `test_names_match_across_accents_and_url_slugs` |
| Phones match on the last 9 digits, so national and international formats agree | [matching.py:74](../src/exposure_auditor/agent/matching.py#L74) | `test_phone_matches_national_format`; case 04 |
| "Not me" is remembered as a blind index and skipped in later scans | [orchestrator.py:388](../src/exposure_auditor/agent/orchestrator.py#L388), [scans.py:61](../src/exposure_auditor/scans.py#L61) | `test_not_me_deletes_the_finding_and_future_scans_skip_it` |

## 3. Text that talks to the agent

| Rule | Enforced | Proven by |
|---|---|---|
| A page containing text aimed at AI agents can never be a confident match, whatever it claims | [matching.py:89](../src/exposure_auditor/agent/matching.py#L89), [orchestrator.py:396](../src/exposure_auditor/agent/orchestrator.py#L396) | `test_pages_that_talk_to_the_agent_never_count_as_likely`; case 05 |
| A refused tool call is returned to the model as an error and the scan continues; only a short code enters the trace | [orchestrator.py:286](../src/exposure_auditor/agent/orchestrator.py#L286) | `test_reverse_image_unavailable_is_reported_not_crashed` |

This rule exists because the eval found the bug. An injected page repeated the
account holder's city back at the agent, earning itself a "likely" match:
corroboration invented by the page itself. Demo precision was 0.875; it is 1.0
now. Claims being checked against the page text — layer 2 — was doing its job
and still wasn't enough, because the page controlled the text.

## 4. What leaves the system

| Rule | Enforced | Proven by |
|---|---|---|
| **No model output ever reaches a third party.** Plans and letters are templates filled from rules; the account holder sends them | [remediation/](../src/exposure_auditor/remediation/) | `test_remediation_plan`, `test_finnish_plan_with_letters_that_follow_the_recipient` |
| Traces carry counts, cost and latency — never page content, findings or identifiers | [tracing.py:36](../src/exposure_auditor/tracing.py#L36) | `test_scan_records_usage_cost_and_a_trace_free_of_personal_data` |
| Password checks are k-anonymous: a 5-character hash prefix, never a password or a full hash | [hibp.py](../src/exposure_auditor/tools/hibp.py) | `test_password_range_accepts_only_a_prefix` |
| An email is only sent to HIBP if the account holder verified it | [breaches.py](../src/exposure_auditor/api/breaches.py) | `test_breach_check_only_for_verified_email` |
| PII is encrypted at rest; lookups go through HMAC blind indexes | [crypto.py](../src/exposure_auditor/crypto.py) | `test_pii_is_encrypted_at_rest` |
| Erasure removes the account's data and leaves the audit log standing | [auth.py](../src/exposure_auditor/api/auth.py) | `test_account_erasure` |

The first row is the one to notice: it is why prompt injection here is a
quality problem rather than a safety incident. The worst an injected page can
do is put a bad row on a screen the account holder reads. It cannot cause a
letter, an email, or any outbound request.

## 5. Budget and blast radius

| Rule | Enforced | Proven by |
|---|---|---|
| 24 model turns and 40 searches per scan | [config.py:48-49](../src/exposure_auditor/config.py#L48) | `test_turn_limit` |
| A scan stops at an estimated-spend ceiling ($1.00), keeping what it found | [orchestrator.py:258](../src/exposure_auditor/agent/orchestrator.py#L258) | `test_a_scan_stops_at_its_cost_ceiling`, `test_no_ceiling_means_the_turn_limit_still_applies` |
| Searches are paced to the provider's limit and rate-limit replies retried, so a scan doesn't burn its budget on refusals | [search.py:75](../src/exposure_auditor/tools/search.py#L75) | `test_parallel_searches_are_paced_not_burst`, `test_a_rate_limited_search_is_retried_after_the_providers_delay` |
| One running scan per account, 5 per day | [config.py:81](../src/exposure_auditor/config.py#L81) | `test_one_scan_at_a_time_and_daily_quota` |
| 30 requests/minute, counted in the database so every replica shares it | [ratelimit.py](../src/exposure_auditor/ratelimit.py) | `test_rate_limits_are_shared_through_the_database` |
| A scan a dead worker abandoned fails instead of hanging | [worker.py](../src/exposure_auditor/worker.py) | `test_worker_fails_scans_a_dead_worker_left_running` |

## 6. Deployment

| Rule | Enforced | Proven by |
|---|---|---|
| Production refuses to write verification codes to a log or a file | [config.py:105](../src/exposure_auditor/config.py#L105) | `test_prod_refuses_console_code_delivery` |
| Production refuses SQLite and refuses demo mode — nobody is shown synthetic findings | [config.py:112](../src/exposure_auditor/config.py#L112) | `test_prod_refuses_demo_scans` |
| The SPA is served under a strict CSP (`script-src 'self'`), with security headers on API responses | [main.py](../src/exposure_auditor/main.py) | `test_spa_served_with_strict_csp`, `test_security_headers_on_api_responses` |
| The donate link must be PayPal over https | [config.py:101](../src/exposure_auditor/config.py#L101) | `test_donate_url_must_be_paypal` |

---

## What isn't guarded

Written down deliberately. A guardrail document that only lists wins is
marketing.

**Attested names and photos are capped, not proven.** You can type any name and
upload any photo once your own email is verified. The cap (3 names, 5 photos)
limits the damage; it doesn't prevent it. Proving a name means an eID or a
document check — a real option in Finland, and the honest fix. Photos are
harder: nothing short of a liveness check ties a face to an account.

**On the invited recruiter instance, verification proves the invite, not the
address.** It sends no mail, so `EA_CODES_ON_PAGE` shows each code on the page,
and anyone holding the invite can verify and scan any email or name. The
ownership gate is reduced to "was invited". That is a deliberate trade for a
small, named audience; the setting is off by default and production refuses it.

**The injection heuristic is a phrase list.** `_AIMED_AT_AGENT` catches "ignore
previous instructions", "note to AI agents" and a handful of relatives. A
politely-worded injection that avoids those phrases passes it. What saves the
scan is defence in depth, not this regex: a claimed identifier still has to be
visible in the text, and a name-only match is still `unclear`. The regex only
has to catch what would otherwise be promoted to `likely`.

**The fixtures were too clean, and it hid a real failure.** Every namesake in
the first seven cases contradicts the account holder -- another city, an
impossible age -- so a name plus a matching city looked like proof, and the
suite reported precision 1.0. On the real web the namesakes shared the city,
and "Tampere" appearing anywhere in a 160-character snippet counted as
corroboration: a politician in Gaziantep and a restaurateur in the right city
both came back as confident matches. Cases 08 and 09 encode exactly that, and
they failed the gate (`namesake_leaks: 3`, `likely_precision: 0.769`) until
the rule changed to require a strong identifier.

**One injection case is an anecdote, not coverage.** Case 05 is a single shape
of attack. Variants worth adding: injection in the title rather than the
snippet, injection that repeats a context detail without any trigger phrase,
and a page that impersonates the system rather than instructing it.

**Rules with a unit test but no eval case:** search-budget exhaustion,
suppression surviving a rescan, and the reverse-image path. Each is proven
against bad input, not against a model trying to get around it.

**"No model output reaches a third party" is structural, not enforced.** It is
true because of how the code is shaped, and nothing fails if a future change
pipes the agent's rationale into a letter template. It deserves a test.

**No global spend cap.** A single scan is now bounded in dollars
(`EA_MAX_SCAN_COST_USD`) as well as in turns and searches, and each account gets
5 scans a day. Nothing bounds the total across accounts, so a crowd of new
registrations can still drain a model or search key. That needs a deployment-wide
budget, and on AWS an alarm on it.

**The broker registry is unverified.** All 11 entries carry
`last_verified: null`, so the plan can send someone to an opt-out procedure
that has changed.

**Refusal handling isn't wired on Bedrock and Foundry.** A model-side refusal
ends the scan cleanly on the Anthropic API; the other two providers lack the
equivalent path.

---

## Adding a guardrail

1. **Enforce it in code, not in the prompt.** If the rule matters when the
   model is adversarial, confused or replaced, a prompt won't hold it.
2. **Unit test the guard function** against the input it must reject.
3. **Add an eval case** with pages designed to tempt a model into routing
   around it, and a threshold in
   [thresholds.yaml](../evals/thresholds.yaml) if it's a hard invariant.
   The three under `guards:` are `max: 0` for every model, scripted or live.
4. **Add a row here**, including what it still doesn't cover.

Before pointing real credentials at real data, `exposure-auditor check` verifies
each dependency with one cheap call and refuses to call the deployment ready
while demo mode is on.
