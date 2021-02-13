profile := kevin

full-deploy:
	sls --aws-profile $(profile) deploy

run-slack-keyword:
	sls --aws-profile $(profile) invoke --function slack_keyword_rank --stage dev --region us-east-1 --data '{"action": "cron", "send_notification": true}'

keyword-logs:
	sls --aws-profile $(profile) logs -f slack_keyword_rank --stage dev --region us-east-1

keyword-logs-tail:
	sls --aws-profile $(profile) logs -f slack_keyword_rank --stage dev --region us-east-1 --tail
