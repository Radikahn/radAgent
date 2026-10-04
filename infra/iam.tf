# Execution role that AgentCore Runtime assumes to run the agent container.
# Baseline statements follow "IAM Permissions for AgentCore Runtime" (execution role section):
# https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html

locals {
  agentcore_logs_prefix = "arn:aws:logs:${var.region}:${local.account_id}:log-group:/aws/bedrock-agentcore/runtimes"

  # Global cross-region inference needs the regional profile, the regional foundation model and the
  # region-less ("global") foundation model; see
  # https://docs.aws.amazon.com/bedrock/latest/userguide/global-cross-region-inference.html
  inference_profile_arns = [
    for id in var.bedrock_model_ids : "arn:aws:bedrock:${var.region}:${local.account_id}:inference-profile/${id}"
  ]
  foundation_model_ids = [for id in var.bedrock_model_ids : trimprefix(id, "global.")]
}

data "aws_iam_policy_document" "runtime_trust" {
  statement {
    sid     = "AssumeRolePolicy"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["bedrock-agentcore.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:aws:bedrock-agentcore:${var.region}:${local.account_id}:*"]
    }
  }
}

resource "aws_iam_role" "runtime" {
  name               = "${var.project}-agentcore-runtime"
  description        = "Execution role for the ${var.project} AgentCore runtime"
  assume_role_policy = data.aws_iam_policy_document.runtime_trust.json
}

data "aws_iam_policy_document" "runtime" {
  # --- AgentCore baseline ---------------------------------------------------------------------

  statement {
    sid       = "ECRImageAccess"
    effect    = "Allow"
    actions   = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
    resources = [aws_ecr_repository.agent.arn]
  }

  statement {
    sid       = "ECRTokenAccess"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid       = "LogGroupAccess"
    effect    = "Allow"
    actions   = ["logs:DescribeLogStreams", "logs:CreateLogGroup"]
    resources = ["${local.agentcore_logs_prefix}/*"]
  }

  statement {
    sid       = "LogResourcePolicy"
    effect    = "Allow"
    actions   = ["logs:PutResourcePolicy"]
    resources = ["${local.agentcore_logs_prefix}/${local.runtime_name}-*"]
  }

  statement {
    sid       = "DescribeLogGroups"
    effect    = "Allow"
    actions   = ["logs:DescribeLogGroups"]
    resources = ["arn:aws:logs:${var.region}:${local.account_id}:log-group:*"]
  }

  statement {
    sid       = "LogStreamWrite"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${local.agentcore_logs_prefix}/*:log-stream:*"]
  }

  statement {
    sid    = "XRay"
    effect = "Allow"
    actions = [
      "xray:PutTraceSegments",
      "xray:PutTelemetryRecords",
      "xray:GetSamplingRules",
      "xray:GetSamplingTargets",
    ]
    resources = ["*"]
  }

  statement {
    sid       = "CloudWatchMetrics"
    effect    = "Allow"
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "cloudwatch:namespace"
      values   = ["bedrock-agentcore"]
    }
  }

  statement {
    sid    = "GetAgentAccessToken"
    effect = "Allow"
    actions = [
      "bedrock-agentcore:GetWorkloadAccessToken",
      "bedrock-agentcore:GetWorkloadAccessTokenForJWT",
      "bedrock-agentcore:GetWorkloadAccessTokenForUserId",
    ]
    resources = [
      "arn:aws:bedrock-agentcore:${var.region}:${local.account_id}:workload-identity-directory/default",
      "arn:aws:bedrock-agentcore:${var.region}:${local.account_id}:workload-identity-directory/default/workload-identity/${local.runtime_name}-*",
    ]
  }

  # --- Bedrock models (global cross-region inference profiles only) ---------------------------

  statement {
    sid       = "InvokeInferenceProfiles"
    effect    = "Allow"
    actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = local.inference_profile_arns
  }

  statement {
    sid       = "InvokeRegionalModelsViaProfiles"
    effect    = "Allow"
    actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = [for m in local.foundation_model_ids : "arn:aws:bedrock:*::foundation-model/${m}"]

    condition {
      test     = "StringEquals"
      variable = "bedrock:InferenceProfileArn"
      values   = local.inference_profile_arns
    }
  }

  statement {
    sid       = "InvokeGlobalModelsViaProfiles"
    effect    = "Allow"
    actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = [for m in local.foundation_model_ids : "arn:aws:bedrock:::foundation-model/${m}"]

    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = ["unspecified"]
    }

    condition {
      test     = "StringEquals"
      variable = "bedrock:InferenceProfileArn"
      values   = local.inference_profile_arns
    }
  }

  # --- Chats bucket ----------------------------------------------------------------------------

  statement {
    sid       = "ChatsList"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.chats.arn]
  }

  statement {
    sid       = "ChatsObjects"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.chats.arn}/*"]
  }

  # --- Secrets ---------------------------------------------------------------------------------

  statement {
    sid       = "AgentSecret"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.agent.arn]
  }

  statement {
    sid       = "GoogleLogin"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue", "secretsmanager:PutSecretValue"]
    resources = [aws_secretsmanager_secret.google.arn]
  }
}

resource "aws_iam_role_policy" "runtime" {
  name   = "${var.project}-agentcore-runtime"
  role   = aws_iam_role.runtime.id
  policy = data.aws_iam_policy_document.runtime.json
}
