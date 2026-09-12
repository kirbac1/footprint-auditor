# Deploying the demo to Cloud Run

```bash
./deploy/cloudrun/deploy.sh <gcp-project-id> [region]
```

**Why here.** Cloud Run's free allowances (2M requests, 360k vCPU-seconds and
180k GiB-seconds a month) are perpetual, it runs the same container as
everything else, and it scales to zero — an idle demo costs nothing. A billing
account is required; nothing is charged within the allowances. Set a budget
alert anyway.

**What the script does.** Enables the APIs, creates the three secrets in Secret
Manager if they are missing, builds the image from this repository with Cloud
Build, and deploys it in demo mode with at most one instance.

**The trade-offs, stated.**

- **Cold starts.** Scaling to zero means the first request after an idle period
  waits for the container to start and the migrations to run — a few seconds.
- **The database is temporary.** SQLite lives in the instance's `/tmp`, which
  is memory, and disappears when the instance does. For a demo that is the
  point: nobody's account outlives the day. For anything real, attach Cloud SQL
  and set `EA_DATABASE_URL`.
- **One instance.** `--max-instances 1` keeps a single SQLite file coherent. It
  is also what keeps a surge inside the free tier.

**Not a demo any more?** Set `EA_DEMO_SCANS=false`, add `EA_BRAVE_API_KEY` and
a model provider, point `EA_DATABASE_URL` at Cloud SQL, and switch
`EA_VERIFICATION_DELIVERY` to something that actually sends mail. Then read
the last section of [../../docs/design.md](../../docs/design.md): the remaining
blockers are a privacy notice, a retention schedule and processor agreements,
not infrastructure.
