# infra

Terraform for running the agent on Amazon Bedrock AgentCore Runtime: chats bucket, ECR repo, Cognito
user pool + app client, a Secrets Manager secret, the runtime's execution role, the runtime itself, and
a monthly budget. One user (the owner). Region defaults to `us-west-2`.

## Before you start

- Don't run this as the account's root user. Create an admin in IAM Identity Center (with MFA), sign in with
  `aws sso login`, and delete the root user's access keys.
- In the Bedrock console for the region, make sure the account can use the models in `bedrock_model_ids`
  (Anthropic models ask for a one-time use-case form).
- Docker with buildx (the image is linux/arm64; Apple Silicon builds it natively) and Terraform >= 1.10.

## First deploy

```sh
# 1. State bucket, once (local state, gitignored)
terraform -chdir=infra/bootstrap init
terraform -chdir=infra/bootstrap apply
terraform -chdir=infra/bootstrap output -raw backend_hcl > infra/backend.hcl

# 2. Main stack without the runtime (image_tag unset)
cp infra/terraform.tfvars.example infra/terraform.tfvars   # set budget_email
terraform -chdir=infra init -backend-config=backend.hcl
terraform -chdir=infra apply

# 3. One-time setup
scripts/create-user.sh you@example.com   # Cognito user, prompts for the password
scripts/put-secrets.sh                   # EXA_API_KEY + SECRET_PROMPT -> Secrets Manager
scripts/migrate-chats.sh                 # agent/.agent/{chats,memory} -> S3 (asks first)

# 4. Build + push the image, then apply with image_tag (creates the runtime)
scripts/deploy-agent.sh
scripts/client-env.sh                    # writes client/.env.production
```

Confirm the budget's subscription email AWS sends to `budget_email`.

## Later

- New agent version: `scripts/deploy-agent.sh` (tags are immutable: `<git sha>-<timestamp>`).
- Any other change: pass the deployed tag, or Terraform plans to remove the runtime (blocked by
  `prevent_destroy`): `terraform -chdir=infra apply -var image_tag=<current tag>`, or just run
  `scripts/deploy-agent.sh`, which forwards extra args to `terraform apply`.
- Rotating secrets: `scripts/put-secrets.sh` again. The value is never in Terraform state.

## Notes

- The app authenticates with Cognito (`USER_PASSWORD_AUTH` or SRP) and sends the **access token** to
  the runtime; the runtime's JWT authorizer checks its `client_id` claim.
- The runtime's log group `/aws/bedrock-agentcore/runtimes/<runtime_id>-DEFAULT` is created here with
  30-day retention right after the runtime. If AgentCore created it first, import it (see
  `runtime.tf`).
- The user pool has `deletion_protection = "ACTIVE"` and the runtime has `prevent_destroy`, so
  `terraform destroy` needs both lifted first.
