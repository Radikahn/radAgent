# The AgentCore runtime. It only exists once an image has been pushed: the first scripts/deploy-agent.sh
# pushes <ecr_url>:<tag> and then applies with -var image_tag=<tag>. After that, deploys (GitHub Actions on
# every push to main, or scripts/deploy-agent.sh) change the image with scripts/update-runtime.sh, so
# Terraform ignores it; everything else here is still Terraform's.
#
# prevent_destroy guards against a later `terraform apply` that forgets -var image_tag: that would
# otherwise plan to destroy the runtime (count -> 0) and the next deploy would get a new ARN, breaking
# client/.env.production. Remove it here if you really mean to tear the runtime down.

resource "aws_bedrockagentcore_agent_runtime" "agent" {
  count = local.create_runtime ? 1 : 0

  agent_runtime_name = local.runtime_name
  description        = "${var.project} Strands agent"
  role_arn           = aws_iam_role.runtime.arn

  agent_runtime_artifact {
    container_configuration {
      container_uri = "${aws_ecr_repository.agent.repository_url}:${var.image_tag}"
    }
  }

  network_configuration {
    network_mode = "PUBLIC"
  }

  protocol_configuration {
    server_protocol = "HTTP"
  }

  authorizer_configuration {
    custom_jwt_authorizer {
      discovery_url   = "https://cognito-idp.${var.region}.amazonaws.com/${aws_cognito_user_pool.main.id}/.well-known/openid-configuration"
      allowed_clients = [aws_cognito_user_pool_client.app.id]
    }
  }

  lifecycle_configuration = [{
    idle_runtime_session_timeout = var.idle_session_timeout_seconds
    max_lifetime                 = var.max_session_lifetime_seconds
  }]

  environment_variables = {
    AWS_REGION         = var.region
    AWS_DEFAULT_REGION = var.region
    RADAGENT_S3_BUCKET = aws_s3_bucket.chats.bucket
    RADAGENT_S3_PREFIX = "chats"
    RADAGENT_SECRET_ID = aws_secretsmanager_secret.agent.arn
    # The Google login the agent keeps, and the only client it accepts one from (any, when empty)
    RADAGENT_GOOGLE_SECRET_ID = aws_secretsmanager_secret.google.arn
    GOOGLE_CLIENT_ID          = var.google_client_id
    NO_COLOR                  = "1"
  }

  # The service validates the role (and pulls the image) on create, so its permissions go first.
  depends_on = [aws_iam_role_policy.runtime]

  lifecycle {
    prevent_destroy = false
    ignore_changes  = [agent_runtime_artifact]
  }
}

# Application logs of the DEFAULT endpoint. AgentCore creates this group itself on the runtime's
# first invocation (with no retention); creating it here right after the runtime sets a 30-day
# retention. If AgentCore got there first, apply fails with ResourceAlreadyExistsException; import it:
#   terraform -chdir=infra import 'aws_cloudwatch_log_group.runtime[0]' \
#     "/aws/bedrock-agentcore/runtimes/<runtime_id>-DEFAULT"
resource "aws_cloudwatch_log_group" "runtime" {
  count = local.create_runtime ? 1 : 0

  name              = "/aws/bedrock-agentcore/runtimes/${aws_bedrockagentcore_agent_runtime.agent[0].agent_runtime_id}-DEFAULT"
  retention_in_days = 30
}
