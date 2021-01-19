import sys
import os
import json
import urllib.parse
from datetime import datetime
import traceback
from datetime import datetime

import requests
from bs4 import BeautifulSoup
import boto3
from loguru import logger

# APP_NAME_MAP = {"AK7KWDFU3": "Nightowl"}

LAMBDA_NAME = "personal-cron-dev-slack_keyword_rank"
DATA_TABLE_NAME = "slack-keyword-searches"
PARTITION_KEY = "query_term"
SORT_KEY = "date"

# SLACK_WEBHOOK_URL = os.environ['SLACK_WEBHOOK_URL']

# sample slack.com/apps/search?q=schedule+message
SLACK_BASE_URL = "https://slack.com/apps/search"
# have to see, but potentially first search page stops at 100. That's totally fine,
# if it's outside that it's not even worth mentioning.


def lambda_handler(event, context):
    logger.debug(f"->{event}<-END")
    action = event.get("action")
    if action == "scrape":
        query_term = event.get("query")
        logger.info(f'[*] scraping Slack search for term: "{query_term}"')
        check_term(event, query_term)
    elif action == "cron":
        # for each term, kick off a scraper - scaling, do this last
        query_requests = get_query_requests_to_check()
        logger.info("Running {} queries", len(query_requests))
        print(query_requests)
        # TODO: better handled with a state machine that limits concurrency, but for now keep it simple
        for qr in query_requests:
            qr["action"] = "scrape"
            # #TODO: adjust the App Id setting to be a list so i can handle multiple in the future
            qr["apps"] = [qr["appId"]]
            # if i want to run and update data without annoying anyone i can leave it off
            if event.get("send_notification"):
                qr["send_notification"] = True
            invoke_individual_run(qr)
    else:
        logger.error("[!] idk what to do with this event it is not expected")


def get_query_requests_to_check():
    if os.environ.get("LOCAL"):
        logger.debug("mock data local")
        return [
            {
                "query": "scheduled messages",
                "appId": "A12345678",
                "owner": "dfd@eamil.com",
                "slackWebhookUrl": "https://fake-webhook",
                "appMappings": "AK7KWDFU3:Nightowl,ACXLJ0LER:Timy,AKQK1GZ0S:Streamly,x",
                "id": 2,
            },
            {
                "query": "requests",
                "appId": "AKQK1GZ0S",
                "owner": "dfs@email.com",
                "slackWebhookUrl": "https://fake-webhook",
                "appMappings": "AK7KWDFU3:Nightowl,ACXLJ0LER:Timy,AKQK1GZ0S:Streamly",
                "id": 3,
            },
            {
                "query": "requests",
                "appId": "A87654321",
                "owner": "lol@aol.edu",
                "id": 4,
            },
        ]

    # Load from sheety.co api that sits on top of GlideApps Spreadsheet
    queries_url = os.environ['SHEETY_URL']
    headers = {"Authorization": f'Bearer {os.environ["SHEETY_BEARER_TOKEN"]}'}
    resp = requests.get(queries_url, headers=headers)
    if resp.status_code == 200:
        data = resp.json()
        return data['queries']
    else:
        logger.error("Failed fetching from sheety - {}:{}", resp.status_code, resp.text)
        raise ValueError("Could not get queries to run from Google Sheet")



def invoke_individual_run(qr):
    # until i have a lot, there's not really a point to farm out the work, it's just good practice
    small_batch = True
    payload = json.dumps(qr)
    logger.debug("Invoke for query: {}", payload)
    if os.environ.get("LOCAL") or small_batch:
        logger.debug("Running event in same invocation, not starting new ones")
        # lambda unloads the json event for us
        lambda_handler(json.loads(payload), None)
    else:
        lambda_client = boto3.client("lambda")
        response = lambda_client.invoke(
            FunctionName=LAMBDA_NAME,
            InvocationType="Event",
            Payload=payload,
        )
        logger.info(response)


def fetch_webpage(url, params):
    if os.environ.get("LOCAL"):
        with open("slack_keyword_rank/test.html", "r") as f:
            return f.read()
    else:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 6.2; Win64; x64; rv:16.0.1) Gecko/20121011 Firefox/16.0.1"
        }
        resp = requests.get(url, headers=headers, params=params)
        logger.info(f"[*] fetched data from url: {resp.url}")
        if resp.status_code != 200:
            logger.error(f"[!] {resp.status_code}: {resp.content}")
            raise ValueError("FAIL")

        # with open('test.html', 'w') as f:
        #     f.write(soup.prettify())
        return resp.content


def check_term(event, query_term):
    app_ids = event.get("apps")
    page_content = fetch_webpage(SLACK_BASE_URL, {"q": query_term})
    soup = BeautifulSoup(page_content, "html.parser")
    app_rows = soup.select(".app_row")
    num_apps = len(app_rows)
    logger.info(f"Found {num_apps} app results for search term")

    results = []
    for row in app_rows:
        curr_id = row.attrs.get("data-app-id")
        if curr_id in app_ids:
            print(curr_id)
            rank = row.attrs.get("data-position")
            results.append(
                {"app_id": curr_id, "search_rank": rank, "total_results": num_apps}
            )
            app_ids.remove(curr_id)

    # handle ones not found on page
    for not_found in app_ids:
        results.append({"app_id": not_found, "search_rank": "Not found in search"})

    try:
        # TODO: start with just saving page content, would be smart to have a schema in future
        # for just the app data that matters
        save_search_data(query_term, app_rows)
    except Exception as e:
        traceback.print_exc()
        logger.error("Ruh roh raggy: {}. Didnt save but keep running", e)

    if event.get("send_notification"):
        # don't spam myself
        send_term_notification(event, query_term, results)
    else:
        logger.info("Not sending notification intentionally")


def save_search_data(query_term, data):
    if os.environ.get("LOCAL"):
        logger.debug("mock saving data")
    else:
        # save the page content for now, then switch it to json in the future
        dynamodb = boto3.resource("dynamodb")
        table = dynamodb.Table(DATA_TABLE_NAME)

        # use utc so I don't have to care about timezones ever
        date = str(datetime.utcnow().date())
        item = {PARTITION_KEY: query_term, SORT_KEY: date, "data": data}
        resp = table.put_item(Item=item)
        logger.info(resp)


def send_term_notification(event, query_term, results):
    bad_map_formatting = False
    if not results:
        logger.warn("No results, nothing to send. Not really an error.")
        return None

    # TODO: when i want to scale out to sending for multiple workspaces
    # if event.get('slack_webhook'):
    #     raise ValueError('[!] cant send a message without a webhook')
    app_name_map = {}
    if event.get('appMappings'):
        try:
            mappings = event.get('appMappings').split(',')
            for mapping in mappings:
                app_id, name = mapping.split(':')
                app_name_map[app_id] = name
        except Exception as e:
            bad_map_formatting = True
            traceback.print_exc()
            logger.error("Ruh roh raggy - Mapping format was messsed up so sending only as ids: {}", e)


    msg = f"*Search ranks for query term `{query_term}`:*\n"
    for r in results:
        msg += f'\n>{app_name_map.get(r["app_id"], r["app_id"])}: {r["search_rank"]}'
        if r.get("total_results"):
            msg += f'/{r["total_results"]}'
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": msg}}]
    if bad_map_formatting:
        blocks.append({
			"type": "context",
			"elements": [
				{
					"type": "mrkdwn",
					"text": "_:warning: Your app mapping format is incorrect, so only able to display App Id_"
				}
			]
		})
    data = {"text": "Updated keyword ranks for your apps.", "blocks": blocks}
    logger.debug(json.dumps(data))
    if not os.environ.get("LOCAL") and event.get('slackWebhookUrl'):
        resp = requests.post(event.get('slackWebhookUrl'), json=data)
        logger.info("{}: {}", resp.status_code, resp.text)


if __name__ == "__main__":
    os.environ["LOCAL"] = "true"
    # cron control run
    # query_requests = [
    #     {
    #         'query': 'schedule message',
    #         'apps': ['AK7KWDFU3']
    #     },
    #     {
    #         'query': 'recurring message',
    #         'apps': ['AK7KWDFU3']
    #     }
    # ]
    # os.environ['query_requests'] = json.dumps(query_requests)

    event = {"action": "cron", "send_notification": True}
    # single event
    # query_term = 'abc'# sys.argv[1]
    # event = {'action': 'scrape', 'query': query_term , 'apps': ['AK7KWDFU3']}
    lambda_handler(event, None)