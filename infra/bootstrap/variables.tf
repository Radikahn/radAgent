variable "region" {
  description = "AWS region for the state bucket (use the same region as the main stack)."
  type        = string
  default     = "us-west-2"
}

variable "project" {
  description = "Project name; the bucket is named <project>-tfstate-<account_id>."
  type        = string
  default     = "radagent"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,30}$", var.project))
    error_message = "project must be lowercase letters, digits and hyphens, starting with a letter (it is used in S3 bucket names)."
  }
}
