# AWS deployment (Terraform)

The same shape as the local Docker Compose service, on AWS:

- a VPC with private subnets for the tasks and the database, and a NAT
  gateway for their outbound calls (Bedrock, HIBP, Brave, GitHub, Bluesky)
- an Application Load Balancer, HTTPS only (TLS 1.2+, HTTP redirects)
- ECS Fargate: `api` behind the load balancer, `worker` running scans, and a
  one-off `migrate` task, all from one image
- RDS for PostgreSQL 17: private, encrypted, 7 days of backups, deletion protection
- Secrets Manager for the database URL and the app's keys, injected at task start
- IAM: tasks can call Claude on Bedrock and send codes through SES and SNS,
  nothing more. There's also an optional OIDC role that lets GitHub Actions
  run the live eval with short-lived credentials.

It has been checked with `terraform validate`. It has **not** been applied:
there was no AWS account to apply it to.

## Before you start

1. **Bedrock model access** for Claude Opus 5 in your region (default `eu-central-1`).
2. **An SES verified identity** for the sender address, and SES production
   access if codes should reach anyone beyond verified test addresses.
3. **An ACM certificate** for your domain, in the same region.
4. **An encrypted remote state backend.** Uncomment the `backend "s3"` block in
   `versions.tf`: the state contains the database password.

## Deploy

```bash
cd infra
terraform init
terraform apply -var image_tag=v1 -var certificate_arn=arn:aws:acm:... \
  -var ses_sender=no-reply@yourdomain.fi -var github_repository=you/your-repo
```

The first apply creates everything, but the tasks can't start until the image
and the keys exist.

**Push the image.** Tags are immutable, so use a new one per release. Build for
ARM64, since the tasks run on Graviton:

```bash
aws ecr get-login-password | docker login --username AWS --password-stdin <ecr_repository_url>
docker buildx build --platform linux/arm64 -t <ecr_repository_url>:v1 --push ..
```

**Store the app's keys** (generate them the same way as `scripts/dev_env.py`).
Keep a copy of the Fernet key somewhere safe: without it, the encrypted
columns can't be read back.

```bash
aws secretsmanager put-secret-value --secret-id <app_secret_arn> --secret-string '{
  "EA_JWT_SECRET": "...", "EA_FIELD_ENCRYPTION_KEY": "...", "EA_BLIND_INDEX_KEY": "...",
  "EA_HIBP_API_KEY": "", "EA_BRAVE_API_KEY": "..."
}'
```

**Migrate, then start the services.** Run this for every release that
changes the schema:

```bash
aws ecs run-task --cluster <cluster> --launch-type FARGATE --task-definition <migrate_task_definition> \
  --network-configuration 'awsvpcConfiguration={subnets=[<private_subnet>],securityGroups=[<app_security_group>]}'
aws ecs update-service --cluster <cluster> --service exposure-auditor-api --force-new-deployment
aws ecs update-service --cluster <cluster> --service exposure-auditor-worker --force-new-deployment
```

## Cost, roughly

Idle, in eu-central-1: NAT gateway ~$35/month, load balancer ~$20, db.t4g.micro
~$15, and three small Fargate tasks ~$45. On top of that, Claude tokens per
scan (see `exposure-auditor stats` and the eval report). The NAT gateway is the
first thing to revisit, for example with VPC endpoints for Bedrock and
Secrets Manager.

## Tearing it down

Deletion protection is on for the database. Turn it off (`deletion_protection = false`,
apply) before `terraform destroy`; a final snapshot is kept.
