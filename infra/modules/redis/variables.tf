variable "name" { type = string }
variable "vpc_id" { type = string }
variable "private_subnet_ids" { type = list(string) }
variable "allowed_security_group_ids" { type = list(string), default = [] }
variable "node_type" { type = string, default = "cache.t4g.micro" }
