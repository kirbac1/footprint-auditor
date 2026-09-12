# Design notes

Why this app is shaped the way it is: which parts are swappable, which are
fixed on purpose, what the evals measure, and what it takes to run it for
real.

Companion documents: [guardrails.md](guardrails.md) (every rule, where it is
enforced, what proves it) and [evals/README.md](../evals/README.md) (the cases
and what they have caught).

---

## 1. One AI component, surrounded by code

![Ports and adapters: the React app and API surround a fixed core of guards, and every outside dependency — model, search, reverse image, code delivery, storage — sits behind a small interface with more than one implementation](modularity.svg)

The scan agent is the only place a model decides anything. Everything else —
who may be scanned, whether a page is about you, what the plan says, what the
letters contain — is ordinary code with tests.

That split is the product, not an implementation detail. A privacy tool whose
answers depend on a model's mood cannot be audited, and a model cannot be held
to a promise. So the model gets the open-ended half (what to search for, what a
page appears to mean) and code keeps the half that must be true every time.

## 2. Plug and play: what is swappable

Every outside dependency sits behind a Protocol with at least two
implementations, one of which is used in tests.

| Port | Interface | Implementations |
|---|---|---|
| Model | `.messages.create(...)` | gpt-oss-120b on Bedrock's OpenAI-compatible endpoint (the live instance); Claude on Bedrock, Foundry or the Anthropic API; any other OpenAI-compatible endpoint (Ollama locally, Mistral, OpenAI, Groq); a scripted model for CI and the demo |
| Web search | `SearchProvider` | Brave, paced for its free tier; a fixture replay for evals; a synthetic web for the scripted demo |
| Reverse image | `ReverseImageProvider` | TinEye; none (the tool is then not offered to the agent) |
| Code delivery | `CodeSender` | AWS SES/SNS; console, optionally shown on the page; an outbox file for tests |
| Storage | SQLAlchemy | PostgreSQL; SQLite for local work, tests and the live instance's `/tmp` |

Swapping the model is one environment variable:

```bash
EA_LLM_PROVIDER=openai      # + EA_OPENAI_BASE_URL, EA_MODEL_ID: gpt-oss-120b on Bedrock (live), Mistral, Groq, …
EA_LLM_PROVIDER=ollama      # a model on your laptop, free, nothing leaves it
EA_LLM_PROVIDER=bedrock     # Claude Opus 5 on AWS
```

**What it costs to swap.** The agent speaks the Anthropic message shape, and
[`openai_compat.py`](../src/exposure_auditor/openai_compat.py) translates that
to OpenAI chat-completions and back: tools out, `tool_calls` back as
`tool_use` blocks, `finish_reason` as `stop_reason`, usage into the fields the
trace records, with retries on transient errors. Two things do not survive the
trip — prompt caching (Anthropic's, which changes cost, not behaviour) and
adaptive thinking. **No guard changes.** That was the design test: if a guard
had needed rewriting for a different model, it was never really enforcing
anything.

The adapter was written for Ollama. When Bedrock's Claude route turned out to
be closed to this account, the same adapter served gpt-oss-120b on Bedrock with
a different base URL and key, and no new code.

## 3. Why these models

**gpt-oss-120b runs the live instance** because it measured best and it was
available. On the account this was deployed from, Bedrock's Messages API
endpoint answered "does not exist" for every Claude model id, including
inference profiles listed as active, and the GPT-5.6 models need an entitlement
from AWS Sales. gpt-oss-120b, on the OpenAI-compatible endpoint, worked first
time, scored highest on the eval, and costs $0.15 / $0.60 per million tokens.
Its weights are open, so the same model could later run on hardware you
control.

**Claude Opus 5 remains the code's default provider** because the hard part of
this job is judgement under ambiguity — is this Maija in Oulu the same person
as my Maija in Helsinki? — and because the Anthropic API is the only provider
here that falls back automatically when a request is refused mid-scan. It has
not been measured on this eval, for the access reasons above.

**A local model is the private option.** A scan sends your name, email, phone
and city to whichever model judges the pages. With Ollama that model is on your
machine, so those details never leave it — the behaviour you would want from a
tool whose subject is your own exposure. It also costs nothing per scan.

**The measured comparison** (same guards; the Qwen and scripted runs predate
cases 08 and 09, the two hardest):

| | scripted (CI) | qwen3:4b | qwen3:8b | qwen3:30b-a3b | gpt-oss-120b |
|---|---|---|---|---|---|
| cases × runs | 7 × 1 | 7 × 2 | 7 × 2 | 7, five sessions | **9 × 2** |
| recall | 0.923 | **0.0** | 0.154 `[0 .. 0.31]` | 0.72 – 1.0 by session | **0.969** `[0.94 .. 1.0]` |
| likely_precision | 1.0 | 1.0\* | 1.0\* | 1.0 | 1.0 |
| namesake_leaks | 0 | 0 | 0 | 0 | 0 |
| findings_outside_corpus | 0 | 0 | 0 | 0 | 0 |
| claims refused per run | 0 | 24 | **78** | 4 – 10 | 1 |
| p95 latency | — | 28 s | 472 s | 39 – 216 s | 25 s |
| cost per case | $0 | $0 | $0 | $0 (local) | ~$0.005 |

\* precision over an empty set: the small models recorded almost nothing.
gpt-oss's cost is its measured tokens at Bedrock's prices; the report's own
cost column used the default Claude prices.

**There is a cliff between 8B and 30B**, and the guards are what make it
visible. A weak model here does not produce plausible-looking nonsense; it
produces claims the page text does not support, 78 of them in a run, and every
one is refused. The 8B is also slower than the 30B despite being a quarter the
size, because it is dense: every parameter fires on every token, while the 30B
is a mixture of experts with about 3B active. Small models are not a cheaper
version of this app. They cannot run it.

**The spread is the other lesson.** One three-run session of the 30B scored
1.0, 0.54 and 0.62 on identical cases. So `eval --repeat N` reports the mean
with the range, and judges invariants by their **worst** run. Two clean runs
and one leak is a leaking agent, not a third of one.

## 4. The guards, in one line each

Full contract with enforcement points and tests in
[guardrails.md](guardrails.md). The shape of it:

- **Ownership.** No scan without a verified email or phone. Usernames need a
  code in a public bio. Names and photos are attested and capped — the honest
  hole, documented rather than hidden. An instance can also require an invite
  code to register at all.
- **Scope.** Every query must name the account holder; `OR`, `|` and
  `AROUND()` are rejected. Enforced in code, because search results are
  attacker-controlled text and a prompt is a request, not a control.
- **Evidence.** A finding can only point at a URL a tool returned this scan,
  and every claimed identifier must be visible in the text the model was given.
- **Confidence.** Only a strong identifier — email, phone, username, photo —
  puts a finding straight into the plan. A name, even with a matching city, is
  a hypothesis the account holder confirms.
- **Namesakes.** A contradicting context detail with no strong identifier means
  a stranger: counted, never stored.
- **Injection.** A page that addresses AI agents can never be a confident
  match, whatever it claims. The eval found that one.
- **Spend.** A per-scan cost ceiling, a search budget, per-account and
  deployment-wide daily caps.
- **Output.** No model output ever reaches a third party. Plans and letters are
  templates; the account holder sends them.

## 5. What the evals measure

Nine cases, each a made-up person with a small labelled web: their pages,
namesakes' pages, and pages written to mislead. The eval runs the real agent
and guards against a replay, so a run is free of search quota, repeatable and
identical across models. Scored: recall, precision of "likely" findings,
namesake leaks, findings outside the corpus, guard interventions, cost and
latency.

Three of those gate at zero for every model, scripted or live: errors,
namesake leaks, findings outside the corpus.

The suite has failed its own gate twice, and both times it was right.

The first run failed on an injected page that repeated the subject's city to
corroborate itself; the fix — pages addressing AI agents are never "likely" —
is now a rule with a test.

The second failure came from outside the suite. A real scan returned a
politician abroad and a restaurateur in the right city as confident matches,
while the eval reported precision 1.0 — because every fixture namesake
contradicted the subject. Cases 08 (a namesake in the same city) and 09 (a
city mentioned in passing) reproduced it, failing with `namesake_leaks: 3`,
and the strong-identifier rule made them pass. The fixtures had been too clean;
the lesson is to write a case for each mistake seen on the real web.

## 6. How this differs from DeleteMe and the rest

Two categories of product exist already, and this is deliberately neither.

**Removal services** (DeleteMe, Incogni and similar) take an authorization and
send removal requests on your behalf, by subscription, mostly to US brokers.
They are useful and they are a different trust model: you hand over your
details and a mandate to act as you. This app never acts for you — it produces
a plan, pre-filled letters and opt-out links, and you send them. That is a
weaker product and an honest one: broker removals involve identity checks only
you can pass, and automating identity verification on someone's behalf is the
wrong thing to be good at.

**People-search aggregators** (Spokeo, BeenVerified, and newer AI ones like
DeepSearch) build a profile of *anyone* from public sources. This app inverts
that: it can only ever be pointed at you, and the ownership gate is the load
bearing wall. The same machinery without that gate is a stalking tool — which
is why DeepSearch is in [our broker registry](../src/exposure_auditor/data/brokers.yaml)
as something to opt out of, not a model to copy.

**Where this one is genuinely better:** it shows its evidence (which of your
details each page actually contained, checked against the page text), it tells
you what it set aside and why, it shows its work live while scanning, it works
in Finnish with Finnish routes (DVV non-disclosure, operator-side Fonecta
removal), and it can run entirely on your own machine so the data never leaves
it.

**Where it is behind:** no removal is performed for you, the broker registry is
12 entries where commercial services track hundreds, and there is no monitoring
— one scan is a snapshot, not a watch.

## 7. Where it should go next

In the order I would do them:

1. **Judge pages, not snippets.** Everything is decided from a URL, title and
   160-character snippet. Fetching the page would settle most `no_identity`
   refusals and much of the namesake guessing.
2. **A website identifier.** You cannot currently tell the app which domains
   are yours, so your own site, a namesake's site and a domain you let go years
   ago are indistinguishable.
3. **A no-model baseline.** Run the same nine cases with fixed query templates
   and the code rules alone. If that comes close, the model is overkill for
   this job, and the numbers should say so rather than the architecture.
4. **Jurisdiction-aware brokers.** Ten of twelve registry entries are US-only;
   a Finnish user's footprint is on Finnish services. The prompt now orders by
   region, but the registry itself needs Finnish and EU entries.
5. **Broker freshness.** Every entry but one is `last_verified: null`.
6. **Monitoring.** A scheduled rescan with a diff is what turns this from an
   audit into a service.
7. **Identity assurance** for names and photos before opening sign-ups to
   strangers — an eID check in Finland.

## 8. Running it on AWS with Bedrock

[`infra/`](../infra/README.md) is Terraform for a production shape: VPC,
HTTPS-only load balancer, ECS Fargate services for the API and the worker, a
one-off migration task, encrypted RDS PostgreSQL, Secrets Manager, and a GitHub
OIDC role for the live eval. It validates; it has not been applied. The live
instance runs on Cloud Run instead (section 9) and calls Bedrock from there.

The Bedrock-specific part, as learned against a real account
([deploy/cloudrun/BEDROCK.md](../deploy/cloudrun/BEDROCK.md) has the detail):

1. **Model access.** There is no request page any more: serverless models
   enable themselves on first invocation. A first use of an Anthropic model
   may ask for use-case details.
2. **Pick the route.**
   - *An open-weight model such as gpt-oss-120b* (what runs live):
     `EA_LLM_PROVIDER=openai`,
     `EA_OPENAI_BASE_URL=https://bedrock-runtime.<region>.amazonaws.com/openai/v1`,
     a Bedrock API key in `EA_OPENAI_API_KEY`.
   - *Claude through the Anthropic SDK*: `EA_LLM_PROVIDER=bedrock`. The default
     client talks to the Messages API endpoint, which authorizes
     `bedrock-mantle:CreateInference`, not `bedrock:InvokeModel`. If every model
     id comes back "does not exist", the account isn't onboarded to that
     endpoint; `EA_BEDROCK_API=invoke` with an inference profile id uses
     InvokeModel instead.
3. **Set the prices.** `EA_PRICE_INPUT_PER_MTOK` / `EA_PRICE_OUTPUT_PER_MTOK`
   come from the Bedrock page; the per-scan cost ceiling is computed from them.
4. **Check before scanning:** `exposure-auditor check` makes one cheap call per
   dependency and names what is missing.

Rough idle cost of the Terraform shape in eu-central-1: NAT gateway
~$35/month, load balancer ~$20, db.t4g.micro ~$15, three small Fargate tasks
~$45, plus tokens per scan. The NAT gateway is the first thing to revisit.

## 9. Putting it online for (almost) nothing

The short answer: **the app can be free to host; the model is not free, but a
good hosted one is cheap enough not to matter at a small scale.**

**What is genuinely free**

- **The web app and API.** Cloud Run's allowances are perpetual (2M requests,
  360k vCPU-seconds, 180k GiB-seconds a month), it runs the same container as
  everything else, and it scales to zero.
- **Web search.** Brave's free tier: 1 query/second, 2,000 queries/month.
- **Password breach checks.** The k-anonymity range API is free. Email breach
  lookups need a paid HIBP key.
- **The model, for you alone.** Ollama on your own machine costs nothing.

**What is not**

Hosting a 30B model for other people means renting a GPU: roughly $0.20–0.50
an hour, $150–350 a month if it stays up. Free inference APIs have rate limits
built for demos and terms that usually forbid serving other people's traffic.
Paying per token is the cheaper route by far: gpt-oss-120b on Bedrock measured
about half a cent per eval case, so a $100 credit covers thousands of scans.

**The options, in order of how real they are:**

1. **Local-only.** Free, private, no hosting. Right for yourself; not a service.
2. **Public app, bring-your-own-key.** Each user pastes their own key. No
   inference cost to you, and no processing of strangers' data on your bill.
3. **Public scripted demo.** `EA_DEMO_SCANS=true` runs the real pipeline
   against a scripted model and synthetic results, with a shared fictional
   account. Free, and the app refuses to pretend the findings are real.
4. **Real, for a handful of invited people.** Cloud Run, Brave's free tier,
   a pay-per-token model, and caps sized to both.

**This repository ships 3 and 4 from one workflow.**
[`deploy-demo.yml`](../.github/workflows/deploy-demo.yml) deploys to Cloud Run
after every green CI run, authenticating through workload identity federation,
so no Google key lives in a repository secret. By default it deploys the
scripted demo; the repository variable `MODEL_PROVIDER=bedrock` deploys the
real variant, which is what the live instance runs:

- gpt-oss-120b on Bedrock and real Brave search;
- registration needs an invite code, and every person gets an account of their
  own, because a shared login over real results would show each visitor the
  previous one's details;
- no mail is sent, so verification codes appear on the page, and the database
  is SQLite in the instance's `/tmp`;
- at most 12 searches and $0.25 a scan, 3 scans per account and 5 a day across
  the deployment, which keeps a month inside Brave's 2,000 queries.

Each variant ends with a check: the workflow reads `/meta` from the new
revision and fails if the scripted demo reports real search, or if the real one
reports the scripted model, real search open to anyone, or no invite. A missing
secret would otherwise produce a quietly wrong deployment.

Codes on the page are the deliberate weak point: verification then proves that
someone holds the invite, not that they own the address. Fine for a few named
people; production refuses the setting, with a test.
[`deploy/huggingface/`](../deploy/huggingface/) does the scripted variant for a
Hugging Face Space, kept for accounts with PRO: their free tier no longer
covers Docker Spaces.

Before letting strangers scan themselves for real, the blockers are not
technical: a privacy notice, a retention schedule, data processing agreements
with every provider, and plausibly a DPIA, because profiling identified people
is on the Article 35 list. Those are the real cost of "online", and no free
tier removes them. Encryption at rest, erasure on request and an audit log are
in place; a privacy notice is not, and it should be written before the instance
is shared beyond people invited by name.
