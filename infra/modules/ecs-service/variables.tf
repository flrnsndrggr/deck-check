variable "name" { type = string }
variable "cluster_arn" { type = string }
variable "cluster_name" { type = string, default = "" }
variable "private_subnet_ids" { type = list(string) }
variable "security_group_ids" { type = list(string) }
variable "container_image" { type = string }
variable "container_port" { type = number }
variable "cpu" { type = number, default = 512 }
variable "memory" { type = number, default = 1024 }
variable "desired_count" { type = number, default = 1 }
variable "environment" { type = map(string), default = {} }
variable "target_group_arn" { type = string, default = "" }
variable "assign_public_ip" { type = bool, default = false }
variable "command" { type = list(string), default = [] }
variable "enable_autoscaling" { type = bool, default = false }
variable "autoscaling_min" { type = number, default = 1 }
variable "autoscaling_max" { type = number, default = 4 }
variable "autoscaling_cpu_target" { type = number, default = 65 }
