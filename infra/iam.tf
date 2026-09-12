data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# Used by ECS itself: pull the image, write logs, read the secrets at start.
resource "aws_iam_role" "execution" {
  name               = "${var.name}-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "execution_secrets" {
  name = "read-app-secrets"
  role = aws_iam_role.execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = [aws_secretsmanager_secret.database_url.arn, aws_secretsmanager_secret.app.arn]
    }]
  })
}

# Used by the app code: call Claude, send verification codes. Nothing else.
data "aws_iam_policy_document" "bedrock_invoke" {
  statement {
    sid = "InvokeClaude"
    # The InvokeModel actions cover Bedrock's model endpoints. If you call
    # Claude through the Bedrock Messages (Mantle) endpoint, check AWS's
    # current action list for it and adjust here.
    actions = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = [
      "arn:aws:bedrock:*::foundation-model/anthropic.*",
      "arn:aws:bedrock:*:${data.aws_caller_identity.current.account_id}:inference-profile/*",
    ]
  }
}

data "aws_iam_policy_document" "task" {
  source_policy_documents = [data.aws_iam_policy_document.bedrock_invoke.json]

  statement {
    sid       = "SendEmailCodes"
    actions   = ["ses:SendEmail"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "ses:FromAddress"
      values   = [var.ses_sender]
    }
  }

  statement {
    sid       = "SendSmsCodes"
    actions   = ["sns:Publish"]
    resources = ["*"] # SMS to a phone number has no resource ARN to scope to
  }
}

resource "aws_iam_role" "task" {
  name               = "${var.name}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy" "task" {
  name   = "app"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task.json
}

# GitHub Actions (eval-live.yml) assumes this through OIDC to run the eval
# against Bedrock: short-lived credentials, main branch only, invoke only.
resource "aws_iam_openid_connect_provider" "github" {
  count          = var.github_repository == "" ? 0 : 1
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_policy_document" "github_assume" {
  count = var.github_repository == "" ? 0 : 1

  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github[0].arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:ref:refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "github_eval" {
  count              = var.github_repository == "" ? 0 : 1
  name               = "${var.name}-github-eval"
  assume_role_policy = data.aws_iam_policy_document.github_assume[0].json
}

resource "aws_iam_role_policy" "github_eval" {
  count  = var.github_repository == "" ? 0 : 1
  name   = "invoke-claude"
  role   = aws_iam_role.github_eval[0].id
  policy = data.aws_iam_policy_document.bedrock_invoke.json
}
