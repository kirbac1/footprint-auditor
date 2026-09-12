resource "aws_ecr_repository" "app" {
  name                 = var.name
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/ecs/${var.name}"
  retention_in_days = 30
}

resource "aws_ecs_cluster" "main" {
  name = var.name

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

locals {
  app_secret_keys = [
    "EA_JWT_SECRET",
    "EA_FIELD_ENCRYPTION_KEY",
    "EA_BLIND_INDEX_KEY",
    "EA_HIBP_API_KEY",
    "EA_BRAVE_API_KEY",
  ]

  # One container shape for API, worker and migrations; only the command differs.
  container = {
    image     = "${aws_ecr_repository.app.repository_url}:${var.image_tag}"
    essential = true
    environment = [
      { name = "EA_ENV", value = "prod" },
      { name = "EA_LLM_PROVIDER", value = "bedrock" },
      { name = "EA_BEDROCK_REGION", value = var.region },
      { name = "EA_SCAN_EXECUTION", value = "worker" },
      { name = "EA_VERIFICATION_DELIVERY", value = "aws" },
      { name = "EA_SES_SENDER", value = var.ses_sender },
    ]
    secrets = concat(
      [{ name = "EA_DATABASE_URL", valueFrom = aws_secretsmanager_secret.database_url.arn }],
      [for key in local.app_secret_keys : { name = key, valueFrom = "${aws_secretsmanager_secret.app.arn}:${key}::" }],
    )
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.app.name
        awslogs-region        = var.region
        awslogs-stream-prefix = "app"
      }
    }
  }

  cli = "/app/.venv/bin/exposure-auditor"
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${var.name}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = var.cpu_architecture
  }

  container_definitions = jsonencode([merge(local.container, {
    name = "api"
    # Migrations run once, as the migrate task below, not in every replica.
    command      = [local.cli, "serve", "--host", "0.0.0.0", "--port", "8000", "--no-migrate"]
    portMappings = [{ containerPort = 8000, protocol = "tcp" }]
    healthCheck = {
      command     = ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"]
      interval    = 15
      timeout     = 5
      retries     = 3
      startPeriod = 20
    }
  })])
}

resource "aws_ecs_task_definition" "worker" {
  family                   = "${var.name}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = var.cpu_architecture
  }

  container_definitions = jsonencode([merge(local.container, {
    name    = "worker"
    command = [local.cli, "worker"]
  })])
}

# Run once per release, before the services update (infra/README.md).
resource "aws_ecs_task_definition" "migrate" {
  family                   = "${var.name}-migrate"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = var.cpu_architecture
  }

  container_definitions = jsonencode([merge(local.container, {
    name    = "migrate"
    command = [local.cli, "migrate"]
  })])
}

resource "aws_ecs_service" "api" {
  name            = "${var.name}-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.api_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.app.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  depends_on = [aws_lb_listener.https]
}

resource "aws_ecs_service" "worker" {
  name            = "${var.name}-worker"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = var.worker_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.app.id]
    assign_public_ip = false
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
}
