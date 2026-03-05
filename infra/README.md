# Deck.Check Infrastructure

Terraform layout for AWS deployment.

## Environments
- `infra/envs/staging`
- `infra/envs/prod`

## Modules
- `modules/network`: VPC, subnets, NAT, routing
- `modules/alb`: ALB, target groups, listener/rules
- `modules/ecs-service`: ECS Fargate service + task definition + logs
- `modules/rds`: PostgreSQL instance + subnet group + SG
- `modules/redis`: ElastiCache Redis + subnet group + SG
- `modules/cloudfront_waf`: CloudFront distribution + WAF ACL (regional baseline)
- `modules/observability`: CloudWatch dashboard and baseline alarms

## Quick Start (staging)
```bash
cd infra/envs/staging
cp terraform.tfvars.example terraform.tfvars
terraform init
terraform plan
terraform apply
```

## Production Notes
- Use Terraform remote state (S3 + DynamoDB lock table) in CI/CD.
- Use ACM certificate in `us-east-1` for CloudFront custom domains.
- Run DB migrations before flipping traffic to new API tasks.
