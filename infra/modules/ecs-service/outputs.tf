output "service_name" { value = aws_ecs_service.this.name }
output "task_definition_arn" { value = aws_ecs_task_definition.this.arn }
output "task_role_arn" { value = aws_iam_role.task.arn }
output "execution_role_arn" { value = aws_iam_role.execution.arn }
