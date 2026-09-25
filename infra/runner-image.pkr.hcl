# Run from infra: AWS_PROFILE=operator packer init runner-image.pkr.hcl
# AWS_PROFILE=operator packer build runner-image.pkr.hcl
packer {
  required_plugins {
    amazon = {
      version = ">= 1.3.0"
      source  = "github.com/hashicorp/amazon"
    }
  }
}

variable "region" {
  type    = string
  default = "us-west-2"
}

source "amazon-ebs" "runner" {
  region        = var.region
  ami_name      = "harness-report-runner-${formatdate("YYYYMMDD-hhmmss", timestamp())}"
  instance_type = "c6i.2xlarge"
  ssh_username  = "ubuntu"
  source_ami_filter {
    filters = {
      name                = "ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"
      virtualization-type = "hvm"
      root-device-type    = "ebs"
    }
    owners      = ["099720109477"]
    most_recent = true
  }
  launch_block_device_mappings {
    device_name           = "/dev/sda1"
    volume_size           = 200
    volume_type           = "gp3"
    encrypted             = true
    delete_on_termination = true
  }
  tags = { Project = "harness-report", Purpose = "prepared-worker-image" }
}

build {
  sources = ["source.amazon-ebs.runner"]
  provisioner "shell" {
    script          = "runner-install.sh"
    execute_command = "chmod +x {{ .Path }}; sudo bash {{ .Path }}"
  }
  provisioner "shell" {
    inline = ["sudo cloud-init clean --logs --machine-id", "sudo rm -f /etc/ssh/ssh_host_*", "sudo rm -rf /home/ubuntu/.ssh /root/.ssh"]
  }
  post-processor "manifest" {
    output = ".build/runner-image-manifest.json"
  }
}
