# GitHub Actions deploys the agent from main (.github/workflows/main.yml): it pushes an image to ECR and points the
# runtime at it with scripts/update-runtime.sh. It signs in with OIDC, so no AWS keys live in GitHub, and only
# workflow runs on the main branch of var.github_repository can assume the role.
#
# Once applied, scripts/ci-vars.sh stores the role and the rest in the repository's Actions variables.

locals {
  create_ci = var.github_repository != ""

  # What GitHub's OIDC sub claim starts with: "repo:<owner>/<name>", or with immutable subjects (the default for
  # newer repositories) "repo:<owner>@<owner id>/<name>@<repo id>"
  github_subject_prefix = coalesce(var.github_oidc_subject_prefix, "repo:${var.github_repository}")

  # Matches the runtime whether or not it exists yet; AgentCore appends "-<10 random characters>" to the name.
  runtime_arn_pattern = "arn:aws:bedrock-agentcore:${var.region}:${local.account_id}:runtime/${local.runtime_name}-*"
}

# One per account per URL. If the account already has it, import it:
#   terraform -chdir=infra import 'aws_iam_openid_connect_provider.github[0]' \
#     arn:aws:iam::<account id>:oidc-provider/token.actions.githubusercontent.com
resource "aws_iam_openid_connect_provider" "github" {
  count = local.create_ci ? 1 : 0

  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_policy_document" "github_actions_trust" {
  count = local.create_ci ? 1 : 0

  statement {
    sid     = "GitHubActionsMain"
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github[0].arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["${local.github_subject_prefix}:ref:refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "github_actions" {
  count = local.create_ci ? 1 : 0

  name               = "${var.project}-github-actions"
  description        = "GitHub Actions on ${var.github_repository}@main: push the agent image and update the runtime"
  assume_role_policy = data.aws_iam_policy_document.github_actions_trust[0].json
}

data "aws_iam_policy_document" "github_actions" {
  statement {
    sid       = "ECRLogin"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid    = "ECRPush"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:CompleteLayerUpload",
      "ecr:GetDownloadUrlForLayer",
      "ecr:InitiateLayerUpload",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
    ]
    resources = [aws_ecr_repository.agent.arn]
  }

  statement {
    sid    = "UpdateRuntime"
    effect = "Allow"
    actions = [
      "bedrock-agentcore:GetAgentRuntime",
      "bedrock-agentcore:UpdateAgentRuntime",
      "bedrock-agentcore:GetAgentRuntimeEndpoint",
    ]
    resources = [local.runtime_arn_pattern, "${local.runtime_arn_pattern}/runtime-endpoint/*"]
  }

  # UpdateAgentRuntime sends the runtime's execution role along with the image.
  statement {
    sid       = "PassRuntimeRole"
    effect    = "Allow"
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.runtime.arn]

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["bedrock-agentcore.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "github_actions" {
  count = local.create_ci ? 1 : 0

  name   = "${var.project}-github-actions"
  role   = aws_iam_role.github_actions[0].id
  policy = data.aws_iam_policy_document.github_actions.json
}
