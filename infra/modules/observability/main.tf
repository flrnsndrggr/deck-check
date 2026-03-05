resource "aws_cloudwatch_metric_alarm" "api_cpu_high" {
  alarm_name          = "${var.name}-api-cpu-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "CPUUtilization"
  namespace           = "AWS/ECS"
  period              = 60
  statistic           = "Average"
  threshold           = 80
  dimensions = {
    ClusterName = var.cluster_name
    ServiceName = var.api_service_name
  }
}

resource "aws_cloudwatch_metric_alarm" "worker_cpu_high" {
  alarm_name          = "${var.name}-worker-cpu-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "CPUUtilization"
  namespace           = "AWS/ECS"
  period              = 60
  statistic           = "Average"
  threshold           = 85
  dimensions = {
    ClusterName = var.cluster_name
    ServiceName = var.worker_service_name
  }
}

resource "aws_cloudwatch_dashboard" "this" {
  dashboard_name = "${var.name}-dashboard"
  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric"
        x = 0
        y = 0
        width = 12
        height = 6
        properties = {
          title = "API CPU"
          metrics = [["AWS/ECS", "CPUUtilization", "ClusterName", var.cluster_name, "ServiceName", var.api_service_name]]
          period = 60
          stat = "Average"
        }
      },
      {
        type = "metric"
        x = 12
        y = 0
        width = 12
        height = 6
        properties = {
          title = "Worker CPU"
          metrics = [["AWS/ECS", "CPUUtilization", "ClusterName", var.cluster_name, "ServiceName", var.worker_service_name]]
          period = 60
          stat = "Average"
        }
      }
    ]
  })
}
