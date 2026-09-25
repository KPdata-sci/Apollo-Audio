# AWS Terraform (future work, not wired up)

This is a consolidated copy of the AWS infrastructure sketch that was previously
duplicated across `DB/` and `testing/Terraform/` (both contained overlapping,
unfinished drafts for the same VPC/EC2/DynamoDB/S3 setup).

**This is not used by the local docker-compose stack** and is not currently
`terraform apply`-able. It's kept as a starting point for if/when this project
moves from "local Docker" to a real AWS deployment (e.g. Lambda + DynamoDB +
S3 instead of the local FastAPI + Postgres + MinIO stack).

Known issues to fix before this is usable:
- `variables.tf` declares `vpc_id`, `public_subnet_ids`, `allowed_ingress_ports`
  etc. that nothing in `main.tf`/`networking.tf` actually sets from the
  `main_vpc`/subnets defined here — the two files were written against
  slightly different variable names and need reconciling.
- `aws_autoscaling_group.ec2_scale` sets `tags` as a list of objects, which is
  the pre-Terraform-0.12 syntax; recent `hashicorp/aws` expects `dynamic "tag"`
  blocks instead.
- No `backend` block — state would default to local, which isn't appropriate
  for anything beyond solo experimentation.
- No IAM least-privilege review has been done on the Lambda/EC2 policies that
  existed in the `testing/Terraform/security.tf` draft (superseded copy, not
  included here) — revisit before granting `AmazonDynamoDBFullAccess`.
