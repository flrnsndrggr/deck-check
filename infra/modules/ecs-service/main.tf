resource "aws_cloudwatch_log_group" "this" {
  name              = "/ecs/${var.name}"
  retention_in_days = 14
}

resource "aws_iam_role" "execution" {
  name = "${var.name}-exec-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Effect = "Allow",
      Principal = { Service = "ecs-tasks.amazonaws.com" },
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "task" {
  name = "${var.name}-task-role"
  assume_role_policy = aws_iam_role.execution.assume_role_policy
}

locals {
  env_list = [for k, v in var.environment : { name = k, value = v }]
  container_base = {
    name      = var.name
    image     = var.container_image
    essential = true
    environment = local.env_list
    portMappings = [{
      containerPort = var.container_port
      hostPort      = var.container_port
      protocol      = "tcp"
    }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.this.name
        awslogs-region        = data.aws_region.current.name
        awslogs-stream-prefix = var.name
      }
    }
  }
  container_def = length(var.command) > 0 ? merge(local.container_base, { command = var.command }) : local.container_base
}

data "aws_region" "current" {}

resource "aws_ecs_task_definition" "this" {
  family                   = var.name
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = tostring(var.cpu)
  memory                   = tostring(var.memory)
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn
  container_definitions    = jsonencode([local.container_def])
}

resource "aws_ecs_service" "this" {
  name            = var.name
  cluster         = var.cluster_arn
  task_definition = aws_ecs_task_definition.this.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = var.security_group_ids
    assign_public_ip = var.assign_public_ip
  }

  dynamic "load_balancer" {
    for_each = var.target_group_arn != "" ? [1] : []
    content {
      target_group_arn = var.target_group_arn
      container_name   = var.name
      container_port   = var.container_port
    }
  }

  lifecycle {
    ignore_changes = [task_definition]
  }
}

resource "aws_appautoscaling_target" "ecs" {
  count              = var.enable_autoscaling && var.cluster_name != "" ? 1 : 0
  max_capacity       = var.autoscaling_max
  min_capacity       = var.autoscaling_min
  resource_id        = "service/${var.cluster_name}/${aws_ecs_service.this.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "cpu_target" {
  count              = var.enable_autoscaling && var.cluster_name != "" ? 1 : 0
  name               = "${var.name}-cpu-target"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.ecs[0].resource_id
  scalable_dimension = aws_appautoscaling_target.ecs[0].scalable_dimension
  service_namespace  = aws_appautoscaling_target.ecs[0].service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value       = var.autoscaling_cpu_target
    scale_in_cooldown  = 120
    scale_out_cooldown = 60
  }
}
