# The state bucket is made by bootstrap.sh before the first init — Terraform cannot create the
# bucket it stores its own state in.  Locking is S3-native (a .tflock object beside the state),
# so there is no DynamoDB lock table to own.
terraform {
  backend "s3" {
    bucket       = "harness-report-tfstate-324037324697"
    key          = "harness-report/terraform.tfstate"
    region       = "us-west-2"
    encrypt      = true
    use_lockfile = true
  }
}
