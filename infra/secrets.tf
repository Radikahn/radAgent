# The agent's secrets (EXA_API_KEY, the SPOTIFY_* keys, SECRET_PROMPT) as one JSON object.
# No aws_secretsmanager_secret_version on purpose: scripts/put-secrets.sh sets the value out of band
# so it never lands in Terraform state.

resource "aws_secretsmanager_secret" "agent" {
  name                    = "${var.project}/agent"
  description             = "Secrets for the ${var.project} agent runtime (set with scripts/put-secrets.sh)"
  recovery_window_in_days = 7
}

# The user's Google login, written by the agent itself when the app connects Google (agent/src/radagent/tools/google/
# account.py), so it's apart from the secret above, which scripts/put-secrets.sh replaces whole.
resource "aws_secretsmanager_secret" "google" {
  name                    = "${var.project}/google"
  description             = "The ${var.project} agent's Google login (written by the agent when the app connects Google)"
  recovery_window_in_days = 7
}
