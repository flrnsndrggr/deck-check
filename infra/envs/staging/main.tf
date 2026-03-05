module "network" {
  source     = "../../modules/network"
  name       = var.name
  cidr_block = var.vpc_cidr
}

module "alb" {
  source            = "../../modules/alb"
  name              = var.name
  vpc_id            = module.network.vpc_id
  public_subnet_ids = module.network.public_subnet_ids
}

resource "aws_security_group" "app" {
  name   = "${var.name}-app-sg"
  vpc_id = module.network.vpc_id

  ingress {
    from_port       = 3000
    to_port         = 3000
    protocol        = "tcp"
    security_groups = [module.alb.security_group_id]
  }

  ingress {
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [module.alb.security_group_id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_ecs_cluster" "this" {
  name = "${var.name}-cluster"
}

resource "aws_ecr_repository" "api" {
  name = "${var.name}-api"
}

resource "aws_ecr_repository" "web" {
  name = "${var.name}-web"
}

module "rds" {
  source                     = "../../modules/rds"
  name                       = var.name
  vpc_id                     = module.network.vpc_id
  private_subnet_ids         = module.network.private_subnet_ids
  db_name                    = var.db_name
  username                   = var.db_username
  password                   = var.db_password
  allowed_security_group_ids = [aws_security_group.app.id]
}

module "redis" {
  source                     = "../../modules/redis"
  name                       = var.name
  vpc_id                     = module.network.vpc_id
  private_subnet_ids         = module.network.private_subnet_ids
  allowed_security_group_ids = [aws_security_group.app.id]
}

locals {
  database_url = "postgresql+psycopg://${var.db_username}:${var.db_password}@${module.rds.endpoint}:${module.rds.port}/${var.db_name}"
  redis_url    = "redis://${module.redis.endpoint}:${module.redis.port}/0"
  api_image    = "${aws_ecr_repository.api.repository_url}:${var.api_image_tag}"
  web_image    = "${aws_ecr_repository.web.repository_url}:${var.web_image_tag}"
}

module "api_service" {
  source             = "../../modules/ecs-service"
  name               = "${var.name}-api"
  cluster_arn        = aws_ecs_cluster.this.arn
  cluster_name       = aws_ecs_cluster.this.name
  private_subnet_ids = module.network.private_subnet_ids
  security_group_ids = [aws_security_group.app.id]
  container_image    = local.api_image
  container_port     = 8000
  desired_count      = 1
  enable_autoscaling = true
  autoscaling_min    = 1
  autoscaling_max    = 4
  target_group_arn   = module.alb.api_target_group_arn
  environment = {
    ENVIRONMENT          = "staging"
    DATABASE_URL         = local.database_url
    REDIS_URL            = local.redis_url
    CARD_CACHE_BACKEND   = "postgres"
    RULES_CACHE_DIR      = "/tmp/rules"
    SCRYFALL_BULK_PATH   = "/tmp/scryfall-oracle-cards.json"
    CORS_ALLOWED_ORIGINS = "https://${length(var.domain_aliases) > 0 ? var.domain_aliases[0] : module.cloudfront.distribution_domain_name}"
    APP_BASE_URL         = "https://${length(var.domain_aliases) > 0 ? var.domain_aliases[0] : module.cloudfront.distribution_domain_name}"
  }
}

module "web_service" {
  source             = "../../modules/ecs-service"
  name               = "${var.name}-web"
  cluster_arn        = aws_ecs_cluster.this.arn
  cluster_name       = aws_ecs_cluster.this.name
  private_subnet_ids = module.network.private_subnet_ids
  security_group_ids = [aws_security_group.app.id]
  container_image    = local.web_image
  container_port     = 3000
  desired_count      = 1
  enable_autoscaling = true
  autoscaling_min    = 1
  autoscaling_max    = 3
  target_group_arn   = module.alb.web_target_group_arn
  environment = {
    NODE_ENV             = "production"
    NEXT_PUBLIC_API_BASE = ""
  }
}

module "worker_service" {
  source             = "../../modules/ecs-service"
  name               = "${var.name}-worker"
  cluster_arn        = aws_ecs_cluster.this.arn
  cluster_name       = aws_ecs_cluster.this.name
  private_subnet_ids = module.network.private_subnet_ids
  security_group_ids = [aws_security_group.app.id]
  container_image    = local.api_image
  container_port     = 8000
  desired_count      = 1
  enable_autoscaling = true
  autoscaling_min    = 1
  autoscaling_max    = 8
  command            = ["python", "-m", "app.workers.rq_worker"]
  environment = {
    ENVIRONMENT        = "staging"
    DATABASE_URL       = local.database_url
    REDIS_URL          = local.redis_url
    CARD_CACHE_BACKEND = "postgres"
  }
}

resource "aws_iam_role" "scheduler" {
  name = "${var.name}-scheduler-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Effect = "Allow",
      Principal = { Service = "events.amazonaws.com" },
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "scheduler" {
  name = "${var.name}-scheduler-policy"
  role = aws_iam_role.scheduler.id
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Action = ["ecs:RunTask"],
        Resource = [module.api_service.task_definition_arn]
      },
      {
        Effect = "Allow",
        Action = ["iam:PassRole"],
        Resource = [module.api_service.execution_role_arn, module.api_service.task_role_arn]
      }
    ]
  })
}

resource "aws_cloudwatch_event_rule" "daily_updates" {
  name                = "${var.name}-daily-updates"
  schedule_expression = "rate(1 day)"
}

resource "aws_cloudwatch_event_target" "daily_updates" {
  rule      = aws_cloudwatch_event_rule.daily_updates.name
  target_id = "update-data"
  arn       = aws_ecs_cluster.this.arn
  role_arn  = aws_iam_role.scheduler.arn

  ecs_target {
    task_count          = 1
    launch_type         = "FARGATE"
    task_definition_arn = module.api_service.task_definition_arn
    network_configuration {
      subnets          = module.network.private_subnet_ids
      security_groups  = [aws_security_group.app.id]
      assign_public_ip = false
    }
  }

  input = jsonencode({
    containerOverrides = [{
      name    = "${var.name}-api"
      command = ["python", "/app/scripts/update_data.py", "--all"]
    }]
  })
}

module "cloudfront" {
  source                   = "../../modules/cloudfront_waf"
  name                     = var.name
  alb_dns_name             = module.alb.alb_dns_name
  aliases                  = var.domain_aliases
  acm_certificate_arn      = var.cloudfront_acm_certificate_arn
}

resource "aws_wafv2_web_acl_association" "alb" {
  resource_arn = module.alb.alb_arn
  web_acl_arn  = module.cloudfront.waf_web_acl_arn
}

resource "aws_route53_record" "site" {
  count   = var.route53_zone_id != "" && var.site_domain != "" ? 1 : 0
  zone_id = var.route53_zone_id
  name    = var.site_domain
  type    = "A"
  alias {
    name                   = module.cloudfront.distribution_domain_name
    zone_id                = module.cloudfront.distribution_hosted_zone_id
    evaluate_target_health = false
  }
}

module "observability" {
  source              = "../../modules/observability"
  name                = var.name
  cluster_name        = aws_ecs_cluster.this.name
  api_service_name    = module.api_service.service_name
  worker_service_name = module.worker_service.service_name
}
