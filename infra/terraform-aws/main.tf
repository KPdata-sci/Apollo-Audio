//--- Providers ---//

terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

# Provider we are using ie AWS
provider "aws" {
  region                  = var.aws_region
  shared_credentials_file = var.shared_credential_file
  profile                 = var.aws_profile
}

//--- VPC ---//

resource "aws_vpc" "main_vpc" {
  cidr_block           = var.vpc_cidr_block
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name = "Main VPC"
  }
}

//--- Subnets ---//
resource "aws_subnet" "private_subnet" {
  vpc_id                  = aws_vpc.main_vpc.id
  cidr_block              = var.private_subnet_cidr
  availability_zone       = var.availability_zone
  map_public_ip_on_launch = false

  tags = {
    Name = "Private Subnet"
  }
}

resource "aws_subnet" "public_subnet" {
  vpc_id                  = aws_vpc.main_vpc.id
  cidr_block              = var.public_subnet_cidr
  availability_zone       = var.availability_zone
  map_public_ip_on_launch = true

  tags = {
    Name = "Public Subnet"
  }
}

//--- EC2 ---//

resource "aws_instance" "private_ec2" {
  ami           = var.ec2_ami
  instance_type = var.instance_type
  subnet_id     = aws_subnet.private_subnet.id

  tags = {
    Name = "Private EC2 Instance"
  }
}

resource "aws_key_pair" "deployer" {
  key_name   = var.key_name
  public_key = var.public_key
}

// Additional EC2 Instance with Network Interface
resource "aws_network_interface" "private_interface" {
  subnet_id   = aws_subnet.private_subnet.id
  private_ips = ["10.0.1.10"]
}

resource "aws_instance" "shuttle_server" {
  ami           = var.ec2_ami
  instance_type = var.instance_type
  key_name      = aws_key_pair.deployer.key_name

  network_interface {
    network_interface_id = aws_network_interface.private_interface.id
    device_index         = 0
  }

  tags = {
    Name = "Shuttle Server"
  }
}

// Launch Template
resource "aws_launch_template" "t2_launch" {
  name_prefix   = "t2_launch_template"
  image_id      = var.ec2_ami
  instance_type = var.instance_type
}

// AutoScaling Group
resource "aws_autoscaling_group" "ec2_scale" {
  desired_capacity = var.desired_capacity
  max_size         = var.max_size
  min_size         = var.min_size

  launch_template {
    id      = aws_launch_template.t2_launch.id
    version = "$Latest"
  }

  vpc_zone_identifier = [aws_subnet.private_subnet.id]
  tags = [
    {
      key                 = "Name"
      value               = "AutoScaling EC2"
      propagate_at_launch = true
    }
  ]
}

//--- S3 Bucket ---//

resource "aws_s3_bucket" "main_bucket" {
  bucket        = var.s3_bucket_name
  force_destroy = true

  tags = {
    Name = "Main S3 Bucket"
  }
}

//--- DynamoDB ---//

resource "aws_dynamodb_table" "basic_dynamodb_table" {
  name         = var.dynamodb_table_name
  billing_mode = var.billing_mode
  read_capacity  = var.read_capacity
  write_capacity = var.write_capacity

  hash_key  = "SongId"
  range_key = "SongEntry"

  attribute {
    name = "SongId"
    type = "S"
  }

  attribute {
    name = "SongEntry"
    type = "S"
  }

  attribute {
    name = "Artist"
    type = "S"
  }

  attribute {
    name = "Title"
    type = "S"
  }

  attribute {
    name = "Url"
    type = "S"
  }

  attribute {
    name = "DownloadedAlready"
    type = "B"
  }

  ttl {
    attribute_name = "TimeToExist"
    enabled        = false
  }
}



//---- Need to add in our SFTP server----//
//----AWS API gateway + Transfer family---//
//--- ELastiSearch---/i/