# infra/

Terraform (>= 1.10, AWS provider) for one owner's stack in `us-west-2` by default: S3 chats bucket
(`storage.tf`), ECR (`registry.tf`), Cognito (`auth.tf`), Secrets Manager (`secrets.tf`), runtime role (`iam.tf`),
AgentCore runtime (`runtime.tf`), GitHub OIDC role for CI (`ci.tf`), logs and budget (`observability.tf`).
`bootstrap/` makes the state bucket. Deploy steps are in `README.md`; you don't need them to edit code.

- One file per concern; add resources to the file they belong to. Every variable has a `description` (full
  sentence, ending in a period) and a `type`, plus `validation` when a bad value would fail late.
- Runtime environment variables are set in `runtime.tf`; anything the client needs goes out through
  `outputs.tf` and `scripts/client-env.sh`.
- Secret *values* never go through Terraform (no `aws_secretsmanager_secret_version`): `scripts/put-secrets.sh`
  sets them out of band. See skill `add-secret`.
- Least privilege: grant the runtime role only the actions and ARNs it uses.
- Image tags are changed by `scripts/update-runtime.sh`, which Terraform ignores.

Checks (what CI runs; no AWS credentials needed):

```sh
terraform fmt -check -recursive infra
for dir in infra infra/bootstrap; do terraform -chdir="$dir" init -backend=false -input=false && terraform -chdir="$dir" validate; done
```

Never run `apply` or anything against the real account unless asked.
