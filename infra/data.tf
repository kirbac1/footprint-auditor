# Postgres and the secrets the tasks read.

resource "aws_db_subnet_group" "main" {
  name       = var.name
  subnet_ids = aws_subnet.private[*].id
}

# This password ends up in Terraform state, which is why the backend must be
# encrypted. The app's own keys (below) are deliberately *not* managed here.
resource "random_password" "db" {
  length  = 32
  special = false
}

resource "aws_db_instance" "main" {
  identifier                   = var.name
  engine                       = "postgres"
  engine_version               = "17"
  instance_class               = var.db_instance_class
  allocated_storage            = 20
  max_allocated_storage        = 100
  storage_encrypted            = true
  db_name                      = "auditor"
  username                     = "auditor"
  password                     = random_password.db.result
  db_subnet_group_name         = aws_db_subnet_group.main.name
  vpc_security_group_ids       = [aws_security_group.db.id]
  publicly_accessible          = false
  multi_az                     = var.db_multi_az
  backup_retention_period      = 7
  auto_minor_version_upgrade   = true
  performance_insights_enabled = true
  deletion_protection          = true
  skip_final_snapshot          = false
  final_snapshot_identifier    = "${var.name}-final"
}

resource "aws_secretsmanager_secret" "database_url" {
  name                    = "${var.name}/database-url"
  description             = "SQLAlchemy URL for the app database"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "database_url" {
  secret_id = aws_secretsmanager_secret.database_url.id
  # RDS for Postgres 15+ requires TLS by default; asyncpg takes it from ?ssl=.
  secret_string = "postgresql+asyncpg://auditor:${random_password.db.result}@${aws_db_instance.main.address}:5432/auditor?ssl=require"
}

# The app's keys: JWT secret, the Fernet key that encrypts PII columns, the
# blind-index HMAC key, and the HIBP and Brave API keys. Terraform creates
# the empty secret; you put the JSON in by hand (infra/README.md). Keeping the
# Fernet key out of state matters: whoever holds it can read every row, and
# losing it makes the data unreadable.
resource "aws_secretsmanager_secret" "app" {
  name                    = "${var.name}/app"
  description             = "JSON: EA_JWT_SECRET, EA_FIELD_ENCRYPTION_KEY, EA_BLIND_INDEX_KEY, EA_HIBP_API_KEY, EA_BRAVE_API_KEY"
  recovery_window_in_days = 7
}
