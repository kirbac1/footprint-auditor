output "url" {
  description = "Point your DNS name (the certificate's) at this load balancer."
  value       = aws_lb.main.dns_name
}

output "ecr_repository_url" {
  value = aws_ecr_repository.app.repository_url
}

output "cluster" {
  value = aws_ecs_cluster.main.name
}

output "migrate_task_definition" {
  value = aws_ecs_task_definition.migrate.family
}

output "private_subnets" {
  value = aws_subnet.private[*].id
}

output "app_security_group" {
  value = aws_security_group.app.id
}

output "app_secret_arn" {
  description = "Put the app's keys here as JSON (infra/README.md)."
  value       = aws_secretsmanager_secret.app.arn
}

output "github_eval_role_arn" {
  description = "Set as the AWS_EVAL_ROLE_ARN repository secret for eval-live.yml."
  value       = one(aws_iam_role.github_eval[*].arn)
}
