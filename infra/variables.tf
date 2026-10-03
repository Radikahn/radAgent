variable "region" {
  description = "AWS region for every regional resource."
  type        = string
  default     = "us-west-2"
}

variable "project" {
  description = "Project name used in resource names."
  type        = string
  default     = "radagent"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,30}$", var.project))
    error_message = "project must be lowercase letters, digits and hyphens, starting with a letter (it is used in S3 bucket names)."
  }
}

variable "image_tag" {
  description = "Tag of the agent image in ECR. The AgentCore runtime is only created when this is non-empty; scripts/deploy-agent.sh sets it."
  type        = string
  default     = ""
}

variable "budget_email" {
  description = "Email address that receives budget alerts."
  type        = string
}

variable "monthly_budget_usd" {
  description = "Monthly cost budget in USD."
  type        = number
  default     = 50
}

variable "bedrock_model_ids" {
  description = "Global cross-region inference profile ids the agent may invoke."
  type        = list(string)
  default = [
    "global.anthropic.claude-sonnet-4-6",
    "global.anthropic.claude-haiku-4-5-20251001-v1:0",
  ]

  validation {
    # iam.tf derives the foundation-model ARNs by stripping "global."; other profile types need other ARNs.
    condition     = alltrue([for id in var.bedrock_model_ids : startswith(id, "global.")])
    error_message = "Every bedrock_model_ids entry must be a global cross-region inference profile id (\"global.<model>\")."
  }
}

variable "idle_session_timeout_seconds" {
  description = "AgentCore idle runtime session timeout, in seconds."
  type        = number
  default     = 1800

  validation {
    condition     = var.idle_session_timeout_seconds >= 60 && var.idle_session_timeout_seconds <= 1209600
    error_message = "idle_session_timeout_seconds must be between 60 and 1209600."
  }
}

variable "max_session_lifetime_seconds" {
  description = "AgentCore maximum runtime session lifetime, in seconds."
  type        = number
  default     = 28800

  validation {
    condition     = var.max_session_lifetime_seconds >= 60 && var.max_session_lifetime_seconds <= 1209600
    error_message = "max_session_lifetime_seconds must be between 60 and 1209600."
  }
}
