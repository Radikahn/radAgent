# Chats (and agent memory) live here; the runtime reads and writes them with its execution role.

resource "aws_s3_bucket" "chats" {
  bucket = "${var.project}-chats-${local.account_id}"
}

resource "aws_s3_bucket_ownership_controls" "chats" {
  bucket = aws_s3_bucket.chats.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "chats" {
  bucket = aws_s3_bucket.chats.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "chats" {
  bucket = aws_s3_bucket.chats.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "chats" {
  bucket = aws_s3_bucket.chats.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "chats" {
  bucket = aws_s3_bucket.chats.id

  rule {
    id     = "expire-noncurrent-and-abort-multipart"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 30
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  # Lifecycle rules on noncurrent versions need versioning in place first.
  depends_on = [aws_s3_bucket_versioning.chats]
}

data "aws_iam_policy_document" "chats_tls_only" {
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.chats.arn,
      "${aws_s3_bucket.chats.arn}/*",
    ]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "chats" {
  bucket = aws_s3_bucket.chats.id
  policy = data.aws_iam_policy_document.chats_tls_only.json

  depends_on = [aws_s3_bucket_public_access_block.chats]
}
