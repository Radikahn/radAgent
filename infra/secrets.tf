# The agent's secrets (EXA_API_KEY, SECRET_PROMPT) as one JSON object.
# No aws_secretsmanager_secret_version on purpose: scripts/put-secrets.sh sets the value out of band
# so it never lands in Terraform state.

resource "aws_secretsmanager_secret" "agent" {
  name                    = "${var.project}/agent"
  description             = "Secrets for the ${var.project} agent runtime (set with scripts/put-secrets.sh)"
  recovery_window_in_days = 7
}
