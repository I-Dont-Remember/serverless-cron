#! /bin/bash

AWS_PROFILE='kevin'

local_dynamo=false
table_name='slack-keyword-searches'
partition_key='query_term'
sort_key='date'

if $local_dynamo; then
    aws_command='aws --endpoint-url http://localhost:4569 --region us-east-1'
else
    aws_command="aws --profile $AWS_PROFILE --region us-east-1"
fi
command="$aws_command dynamodb create-table"
$command  \
    --table-name "$table_name" \
    --attribute-definitions "AttributeName=$partition_key,AttributeType=S" "AttributeName=$sort_key,AttributeType=S" \
    --key-schema "AttributeName=$partition_key,KeyType=HASH" "AttributeName=$sort_key,KeyType=RANGE" \
    --billing-mode PAY_PER_REQUEST
