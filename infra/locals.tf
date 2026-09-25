locals {
  name = var.project

  # The canonical host.  www redirects to it at the edge (see site.tf) so there is exactly one
  # origin in play — which is what lets serve.py keep its same-origin check on POST.
  host    = var.domain
  aliases = [var.domain, "www.${var.domain}"]

  account = data.aws_caller_identity.me.account_id

  # Everything the Lambda needs from the repo.  Listed here rather than zipped by a build step so
  # `terraform apply` on its own is a deploy.
  lambda_files = toset(concat(
    ["serve.py", "auth.py", "evals.py"],
    tolist(fileset("${path.module}/..", "lib/*.py")),
  ))

  # Written by Terraform as SecureStrings with a placeholder, then filled once by hand or by
  # bootstrap.sh.  Their values are deliberately not in state: `ignore_changes` keeps them out.
  secrets = ["GITHUB_CLIENT_SECRET", "SESSION_SECRET", "GITHUB_APP_KEY"]

  tags = {
    Project   = var.project
    ManagedBy = "terraform"
    Repo      = var.github_repo
  }
}
