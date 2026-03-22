#!/bin/bash
# LocalStack initialization — creates S3 bucket and SQS FIFO queue for local development

echo "Initializing LocalStack resources..."

# Create S3 bucket
awslocal s3 mb s3://pointcloud-platform
awslocal s3api put-bucket-cors --bucket pointcloud-platform --cors-configuration '{
  "CORSRules": [{
    "AllowedHeaders": ["*"],
    "AllowedMethods": ["GET", "PUT", "POST", "DELETE", "HEAD"],
    "AllowedOrigins": ["http://localhost:5173", "http://localhost:3000"],
    "ExposeHeaders": ["ETag"]
  }]
}'

# Create SQS FIFO queue for processing jobs
awslocal sqs create-queue \
  --queue-name processing-jobs.fifo \
  --attributes FifoQueue=true,ContentBasedDeduplication=false

echo "LocalStack resources initialized:"
echo "  S3 bucket: s3://pointcloud-platform"
echo "  SQS queue: http://localhost:4566/000000000000/processing-jobs.fifo"
