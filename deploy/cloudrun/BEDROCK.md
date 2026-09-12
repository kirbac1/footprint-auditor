# Putting a real model behind the demo

The hosted demo replaces the *web*, not the model. With Bedrock credentials it
runs the real agent — real tool calls, real trace, real token counts — over
synthetic pages, so no real person's data is ever involved and a scan costs
cents rather than the price of one with forty live searches.

## What actually works, and why

Three routes were tried against a real account before this one:

- **Claude through the Messages API endpoint** (`bedrock-mantle`): every model
  id returned "does not exist", including ids and inference profiles that
  `aws bedrock list-foundation-models` showed as active. The account is not
  onboarded to that endpoint.
- **GPT-5.6 Luna, Terra and GPT-6 Astra** on the OpenAI-compatible endpoint:
  "not available for this account" — an entitlement that needs AWS Sales.
- **gpt-oss-120b** on the same endpoint: works, and measured best of every
  model this project has tried — recall 0.969 over nine cases including the
  same-city namesake cases, no leaks, 25 s at p95, about half a cent a case at
  $0.15 / $0.60 per million tokens.

So the demo runs gpt-oss-120b through Bedrock's OpenAI-compatible endpoint,
with a Bedrock API key, using the same adapter that serves Ollama locally. No
new code was needed to add the provider; that is the point of the adapter.

## 1. On AWS (yours to do: I don't create credentials)

**Model access.** Nothing to request: AWS retired the model-access page, and
serverless foundation models enable themselves the first time an account
invokes them. Two caveats remain. A first-time user of an Anthropic model may
be asked for use-case details before the first call succeeds, and a model
served through AWS Marketplace has to be invoked once by someone with
Marketplace permissions to enable it account-wide. `eu-central-1` keeps
inference in the EU; confirm the model is offered there, since availability
still varies by region.

**A user that can do exactly one thing.** IAM → Users → create
`footprint-bedrock`, no console access, with this inline policy. Note the
service prefix: the SDK talks to the Messages-API endpoint on Bedrock (the
"Mantle" client), which authorizes on `bedrock-mantle:CreateInference` against
a *project*, not `bedrock:InvokeModel` against a foundation model. Granting
only the latter produces a 403 that names the missing action, which is how
this was found.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "MessagesApiOnBedrock",
      "Effect": "Allow",
      "Action": "bedrock-mantle:CreateInference",
      "Resource": "arn:aws:bedrock-mantle:*:<your-account-id>:project/*"
    },
    {
      "Sid": "LegacyInvokeModelPath",
      "Effect": "Allow",
      "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
      "Resource": "arn:aws:bedrock:*::foundation-model/anthropic.claude-opus-5*"
    }
  ]
}
```

The second statement is the older InvokeModel path, kept so the key still works
if the client is ever switched back to it. Neither statement grants anything
else: no S3, no instances, no billing.

Then create an access key for it. That key can invoke one model family and
nothing else: it cannot read S3, create instances or see your bill.

## 2. Store the key

Generate a Bedrock API key (console → Bedrock → API keys), put it in `.env` as
`EA_OPENAI_API_KEY` for local use, then:

```bash
./deploy/cloudrun/set-bedrock-api-key.sh
```

It reads the key from `.env`, or asks with a hidden prompt; makes one real call
to the model with it, with the header on stdin rather than the command line;
and stores it in Secret Manager only if that call succeeds.

## 3. Turn it on

```bash
gh variable set MODEL_PROVIDER --body bedrock
gh workflow run deploy-demo
```

The Bedrock variant closes registration and stops publishing the demo
credentials, and the deploy fails if the running service reports the scripted
model — which is what a missing secret would otherwise produce, silently.

## What it costs, and what stops it

gpt-oss-120b is $0.15 per million input tokens and $0.60 per million output.
A demo scan measured about half a cent; a real scan with forty live searches
would be a few cents. Three limits apply anyway, each settable as a repository
variable:

| variable | default here | what it bounds |
|---|---|---|
| `EA_MAX_SCAN_COST_USD` | 0.25 | one scan, by estimated spend |
| `EA_SCANS_PER_DAY` | 10 | one account |
| `EA_SCANS_PER_DAY_TOTAL` | 100 | **the whole deployment** — the wallet |

At half a cent a scan, the deployment-wide cap bounds a bad day at about fifty
cents. Set an AWS budget alert as well: the caps are estimates computed from
`EA_PRICE_*_PER_MTOK`, and an estimate is not a bill.
