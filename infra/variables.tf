variable "region" {
  description = "AWS region. Claude Opus 5 must be enabled in Bedrock here, and it sets where personal data is processed."
  type        = string
  default     = "eu-central-1"
}

variable "name" {
  description = "Prefix for every resource."
  type        = string
  default     = "exposure-auditor"
}

variable "image_tag" {
  description = "Tag of the image in the ECR repository to run (tags are immutable)."
  type        = string
}

variable "certificate_arn" {
  description = "ACM certificate for the load balancer's HTTPS listener."
  type        = string
}

variable "ses_sender" {
  description = "Verified SES address that sends verification codes."
  type        = string
}

variable "cpu_architecture" {
  description = "ARM64 (Graviton, cheaper; build with --platform linux/arm64) or X86_64."
  type        = string
  default     = "ARM64"

  validation {
    condition     = contains(["ARM64", "X86_64"], var.cpu_architecture)
    error_message = "cpu_architecture must be ARM64 or X86_64."
  }
}

variable "api_count" {
  description = "API tasks behind the load balancer."
  type        = number
  default     = 2
}

variable "worker_count" {
  description = "Scan worker tasks."
  type        = number
  default     = 1
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.micro"
}

variable "db_multi_az" {
  description = "Standby replica in a second AZ. Doubles the database cost."
  type        = bool
  default     = false
}

variable "github_repository" {
  description = "owner/name of the GitHub repo allowed to assume the eval role through OIDC. Empty skips it."
  type        = string
  default     = ""
}
