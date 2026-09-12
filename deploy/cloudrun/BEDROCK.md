# The real variant: gpt-oss-120b on Bedrock, real search, invited people

This is what the live instance runs: the real agent driven by gpt-oss-120b on
Amazon Bedrock, searching the real web through Brave, for people you invite.
Each of them registers an account of their own.

## What actually works, and why

Three routes were tried against a real account before this one:

- **Claude through the Messages API endpoint** (`bedrock-mantle`): every model
  id returned "does not exist", including ids and inference profiles that
  `aws bedrock list-foundation-models` showed as active. The account is not
  onboarded to that endpoint.
- **GPT-5.6 Luna, Terra and GPT-6 Astra** on the OpenAI-compatible endpoint:
  "not available for this account" — an entitlement that needs AWS Sales.
- **gpt-oss-120b** on the same endpoint: works, and measured best of every
  model this project has evaluated — recall 0.969 across two runs of all nine
  cases, including the same-city namesake cases, no leaks, 25 s at p95, about
  half a cent a case at $0.15 / $0.60 per million tokens.

So the instance runs gpt-oss-120b through Bedrock's OpenAI-compatible
endpoint, with a Bedrock API key, using the same adapter that serves Ollama
locally. No new code was needed to add the provider; that is the point of the
adapter.

Model access needs no request: AWS retired the model-access page, and
serverless models enable themselves on first invocation. `eu-central-1` keeps
inference in the EU.

## 1. The model key

Generate a Bedrock API key (console → Bedrock → API keys) with an expiry, put
it in `.env` as `EA_OPENAI_API_KEY` for local use, then:

```bash
./deploy/cloudrun/set-bedrock-api-key.sh
```

It reads the key from `.env`, or asks with a hidden prompt; makes one real call
to the model with it, with the header on stdin rather than the command line;
and stores it in Secret Manager only if that call succeeds.

## 2. The search key and the invite

```bash
./deploy/cloudrun/set-brave-key.sh      # from .env; one test query before storing
./deploy/cloudrun/set-invite-code.sh    # prints the code and an invite link, once
```

Send people the invite link: `?invite=` fills the code in on the sign-up form.
Without the code, registration answers 403, and a wrong code is
indistinguishable from a missing one. Run the script again to rotate the code.

There is no shared login. With real search, one account would show every
visitor the previous one's name, email and findings.

## 3. Turn it on

```bash
gh variable set MODEL_PROVIDER --body bedrock
gh workflow run deploy-demo
```

The deploy fails unless the running service reports a real model, real search
and invite-only registration — a missing secret would otherwise produce a
scripted or open instance, silently. To go back to the scripted demo, delete
the variable.

## What the instance does differently, on purpose

- **No mail is sent.** `EA_CODES_ON_PAGE` shows each verification code on the
  page. That means verification proves someone holds the invite, not that they
  own the address: anyone invited can scan any email or name. Acceptable for a
  small invited audience; production refuses the setting outright.
- **Accounts live in `/tmp`.** They disappear when the instance scales down. A
  visitor who comes back tomorrow registers again.
- **No breach lookups.** There is no HIBP key; password checks still work.

## What it costs, and what stops it

gpt-oss-120b is $0.15 per million input tokens and $0.60 per million output.
An eval case measured about half a cent. Every limit is settable as a
repository variable:

| variable | here | what it bounds |
|---|---|---|
| `EA_AGENT_MAX_SEARCHES` | 12 | one scan, by live searches |
| `EA_MAX_SCAN_COST_USD` | 0.25 | one scan, by estimated spend |
| `EA_SCANS_PER_DAY` | 3 | one account |
| `EA_SCANS_PER_DAY_TOTAL` | 5 | **the whole deployment**: the wallet and the search quota |

Five scans of twelve searches a day stays under Brave's 2,000 free queries a
month, and bounds a bad day's model spend at about a dollar even if every scan
hit its ceiling. Set an AWS budget alert as well: the caps are estimates
computed from `EA_PRICE_*_PER_MTOK`, and an estimate is not a bill.

## If you want Claude instead

Claude on Bedrock goes through the Anthropic SDK (`EA_LLM_PROVIDER=bedrock`).
Its default client uses the Messages API endpoint, which authorizes on
`bedrock-mantle:CreateInference` against a *project*, not `bedrock:InvokeModel`
against a foundation model; granting only the latter produces a 403 that names
the missing action. A policy covering both paths:

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
      "Sid": "InvokeModelPath",
      "Effect": "Allow",
      "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
      "Resource": "arn:aws:bedrock:*::foundation-model/anthropic.claude-opus-5*"
    }
  ]
}
```

If the account isn't onboarded to the Messages API endpoint, set
`EA_BEDROCK_API=invoke` and an inference profile id in `EA_MODEL_ID`. A
first-time user of an Anthropic model may be asked for use-case details before
the first call succeeds. Run `exposure-auditor check` and the eval before
switching the deployment over.
