resource "aws_security_group" "this" {
  name   = "${var.name}-alb-sg"
  vpc_id = var.vpc_id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_lb" "this" {
  name               = "${var.name}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.this.id]
  subnets            = var.public_subnet_ids
}

resource "aws_lb_target_group" "web" {
  name        = "${var.name}-web-tg"
  port        = 3000
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"
  health_check {
    path = "/"
  }
}

resource "aws_lb_target_group" "api" {
  name        = "${var.name}-api-tg"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"
  health_check {
    path = "/health"
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.web.arn
  }
}

resource "aws_lb_listener_rule" "api" {
  listener_arn = aws_lb_listener.http.arn
  priority     = 10
  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
  condition {
    path_pattern {
      values = ["/api/*", "/health*", "/docs*", "/openapi.json"]
    }
  }
}
