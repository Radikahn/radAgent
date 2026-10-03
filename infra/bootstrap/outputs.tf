output "bucket" {
  description = "Name of the Terraform state bucket."
  value       = aws_s3_bucket.tfstate.bucket
}

output "backend_hcl" {
  description = "Contents for infra/backend.hcl: terraform -chdir=infra/bootstrap output -raw backend_hcl > infra/backend.hcl"
  value       = <<-EOT
    bucket       = "${aws_s3_bucket.tfstate.bucket}"
    key          = "${var.project}/terraform.tfstate"
    region       = "${var.region}"
    use_lockfile = true
    encrypt      = true
  EOT
}
