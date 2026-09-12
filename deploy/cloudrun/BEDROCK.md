# Putting a real model behind the demo

The hosted demo replaces the *web*, not the model. With Bedrock credentials it
runs the real agent — real tool calls, real trace, real token counts — over
synthetic pages, so no real person's data is ever involved and a scan costs
cents rather than the price of one with forty live searches.

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
`footprint-bedrock`, no console access, with this inline policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
    "Resource": "arn:aws:bedrock:*::foundation-model/anthropic.claude-opus-5*"
  }]
}
```

Then create an access key for it. That key can invoke one model family and
nothing else: it cannot read S3, create instances or see your bill.

## 2. Store the key

```bash
./deploy/cloudrun/set-bedrock-key.sh
```

It prompts for both halves with the prompt visible and the typing hidden,
trims stray whitespace from a paste, warns if the two look swapped, and checks
the pair against AWS before storing anything — a key that AWS rejects never
reaches Secret Manager. Neither half is ever a command-line argument, where
`ps` would show it, and both are dropped from the shell afterwards. Re-running
it adds a new version rather than failing on a conflict.

## 3. Turn it on

```bash
gh variable set MODEL_PROVIDER --body bedrock
gh variable set EA_BEDROCK_REGION --body eu-central-1
# If invoking the bare model id fails with a validation error naming an
# inference profile, set the id it asks for:
#   aws bedrock list-inference-profiles
# gh variable set EA_MODEL_ID --body eu.anthropic.claude-opus-5-...
gh workflow run deploy-demo
```

The workflow then deploys the Bedrock variant, which also closes registration
and stops publishing the demo credentials: the people you send the link and
the credentials to are the only ones who can spend the budget.

## What it costs, and what stops it

A demo scan is a handful of model calls over synthetic pages — cents, not the
~$0.50 a real scan with live search costs. Three limits apply anyway, each
settable as a repository variable:

| variable | default here | what it bounds |
|---|---|---|
| `EA_MAX_SCAN_COST_USD` | 0.50 | one scan, by estimated spend |
| `EA_SCANS_PER_DAY` | 5 | one account |
| `EA_SCANS_PER_DAY_TOTAL` | 40 | **the whole deployment** — the wallet |

Set an AWS budget alert as well. The caps are computed from
`EA_PRICE_*_PER_MTOK`, so put the Bedrock prices in those variables or the
ceiling is calibrated to the wrong number.
