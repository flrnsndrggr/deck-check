output "alb_dns_name" { value = aws_lb.this.dns_name }
output "alb_arn" { value = aws_lb.this.arn }
output "security_group_id" { value = aws_security_group.this.id }
output "web_target_group_arn" { value = aws_lb_target_group.web.arn }
output "api_target_group_arn" { value = aws_lb_target_group.api.arn }
