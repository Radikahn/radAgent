output "region" {
  description = "AWS region of the stack."
  value       = var.region
}

output "account_id" {
  description = "AWS account id."
  value       = local.account_id
}

output "bucket" {
  description = "Chats bucket name."
  value       = aws_s3_bucket.chats.bucket
}

output "ecr_url" {
  description = "ECR repository URL for the agent image (without a tag)."
  value       = aws_ecr_repository.agent.repository_url
}

output "user_pool_id" {
  description = "Cognito user pool id."
  value       = aws_cognito_user_pool.main.id
}

output "client_id" {
  description = "Cognito app client id (public client, no secret)."
  value       = aws_cognito_user_pool_client.app.id
}

output "secret_id" {
  description = "Name of the agent's Secrets Manager secret."
  value       = aws_secretsmanager_secret.agent.name
}

output "secret_arn" {
  description = "ARN of the agent's Secrets Manager secret."
  value       = aws_secretsmanager_secret.agent.arn
}

output "runtime_arn" {
  description = "AgentCore runtime ARN; null until an image_tag has been applied."
  value       = one(aws_bedrockagentcore_agent_runtime.agent[*].agent_runtime_arn)
}

output "github_repository" {
  description = "GitHub repository that deploys the agent; empty when there is no CI role."
  value       = var.github_repository
}

output "github_actions_role_arn" {
  description = "Role GitHub Actions assumes to deploy the agent; null when github_repository is empty."
  value       = one(aws_iam_role.github_actions[*].arn)
}
