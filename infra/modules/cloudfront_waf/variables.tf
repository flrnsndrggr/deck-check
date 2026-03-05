variable "name" { type = string }
variable "alb_dns_name" { type = string }
variable "aliases" { type = list(string), default = [] }
variable "acm_certificate_arn" { type = string, default = "" }
