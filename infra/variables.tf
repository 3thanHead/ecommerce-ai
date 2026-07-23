variable "bucket_name" {
  description = "Globally-unique S3 bucket name for the static site (e.g. codecalm-store-ethan)"
  type        = string
}

variable "aws_region" {
  description = "Region for the bucket (CloudFront is global regardless)"
  type        = string
  default     = "us-east-1"
}
