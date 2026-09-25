variable "aws_region" {
  description = "The AWS region to deploy resources in"
  default     = "eu-west-2"
}

variable "shared_credential_file" {
  description = "Path to the AWS credentials file"
  default     = "~/.aws/credentials"
}

variable "aws_profile" {
  description = "The AWS CLI profile to use"
  default     = "vim"
}

variable "vpc_cidr_block" {
  description = "The CIDR block for the VPC"
  default     = "10.0.0.0/16"
}

variable "private_subnet_cidr" {
  description = "The CIDR block for the private subnet"
  default     = "10.0.1.0/24"
}

variable "public_subnet_cidr" {
  description = "The CIDR block for the public subnet"
  default     = "10.0.0.0/24"
}

variable "availability_zone" {
  description = "The availability zone for the subnets"
  default     = "eu-west-2a"
}

variable "ec2_ami" {
  description = "AMI ID for the EC2 instances"
  default     = "ami-12345678" # Replace with a valid AMI ID
}

variable "instance_type" {
  description = "Instance type for EC2 instances"
  default     = "t2.micro"
}

variable "key_name" {
  description = "Key pair name for SSH access"
  default     = "shuttle_key"
}

variable "public_key" {
  description = "Public SSH key for the key pair"
  default     = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAACAQC7..." # Replace with your public key
}

variable "s3_bucket_name" {
  description = "Name of the S3 bucket"
  default     = "terraform-data-bucket"
}

variable "dynamodb_table_name" {
  description = "Name of the DynamoDB table"
  default     = "MusicData"
}

variable "billing_mode" {
  description = "Billing mode for DynamoDB (PROVISIONED or PAY_PER_REQUEST)"
  default     = "PROVISIONED"
}

variable "read_capacity" {
  description = "Read capacity for DynamoDB table"
  default     = 20
}

variable "write_capacity" {
  description = "Write capacity for DynamoDB table"
  default     = 20
}

variable "desired_capacity" {
  description = "Desired number of instances in the autoscaling group"
  default     = 1
}

variable "max_size" {
  description = "Maximum number of instances in the autoscaling group"
  default     = 3
}

variable "min_size" {
  description = "Minimum number of instances in the autoscaling group"
  default     = 1
}


// VPC Variables
variable "vpc_id" {
  description = "The ID of the VPC"
}

variable "public_subnet_cidrs" {
  description = "List of CIDR blocks for public subnets"
  type        = list(string)
  default     = ["10.0.1.0/24", "10.0.2.0/24"]
}

variable "private_subnet_cidrs" {
  description = "List of CIDR blocks for private subnets"
  type        = list(string)
  default     = ["10.0.3.0/24", "10.0.4.0/24"]
}

variable "availability_zones" {
  description = "List of availability zones"
  type        = list(string)
  default     = ["eu-west-2a", "eu-west-2b"]
}

// Security Group Variables
variable "allowed_ingress_ports" {
  description = "List of allowed ingress ports and protocols"
  type = list(object({
    from_port   = number
    to_port     = number
    protocol    = string
    cidr_blocks = list(string)
  }))
  default = [
    {
      from_port   = 22
      to_port     = 22
      protocol    = "tcp"
      cidr_blocks = ["0.0.0.0/0"]
    },
    {
      from_port   = 443
      to_port     = 443
      protocol    = "tcp"
      cidr_blocks = ["0.0.0.0/0"]
    }
  ]
}

// NAT Gateway Variables
variable "public_subnet_ids" {
  description = "List of public subnet IDs for NAT Gateway placement"
  type        = list(string)
}

// Tag Variables
variable "tags" {
  description = "Default tags for resources"
  type        = map(string)
  default     = {
    Environment = "Development"
    ManagedBy   = "Terraform"
  }
}
