resource "aws_elasticache_subnet_group" "this" {
  name       = "${var.name}-redis-subnets"
  subnet_ids = var.private_subnet_ids
}

resource "aws_security_group" "this" {
  name   = "${var.name}-redis-sg"
  vpc_id = var.vpc_id

  dynamic "ingress" {
    for_each = var.allowed_security_group_ids
    content {
      from_port       = 6379
      to_port         = 6379
      protocol        = "tcp"
      security_groups = [ingress.value]
      description     = "Allow app access"
    }
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_elasticache_cluster" "this" {
  cluster_id           = "${var.name}-redis"
  engine               = "redis"
  node_type            = var.node_type
  num_cache_nodes      = 1
  parameter_group_name = "default.redis7"
  port                 = 6379
  subnet_group_name    = aws_elasticache_subnet_group.this.name
  security_group_ids   = [aws_security_group.this.id]
}
