output "cloudfront_domain" { value = module.cloudfront.distribution_domain_name }
output "alb_dns_name" { value = module.alb.alb_dns_name }
output "api_service" { value = module.api_service.service_name }
output "web_service" { value = module.web_service.service_name }
output "worker_service" { value = module.worker_service.service_name }
output "ecs_cluster_name" { value = aws_ecs_cluster.this.name }
output "api_ecr_repo" { value = aws_ecr_repository.api.repository_url }
output "web_ecr_repo" { value = aws_ecr_repository.web.repository_url }
