import sys
import os
import json
import urllib.parse
from datetime import datetime
import traceback
from datetime import datetime
from copy import deepcopy

import requests
from bs4 import BeautifulSoup
import boto3
from loguru import logger
from unittest.mock import MagicMock
from faunadb import query as q
from faunadb.objects import Ref
from faunadb.client import FaunaClient

LAMBDA_NAME = "personal-cron-dev-slack_keyword_rank"
DATA_TABLE_NAME = "slack-keyword-searches"
PARTITION_KEY = "query_term"
SORT_KEY = "date"
FAUNA_SECRET = os.environ.get('FAUNA_SECRET')
KEYWORD_COLLECTION = 'keywords'
# Should be same for life of the Lambda
UTC_DATE = str(datetime.utcnow().date())
# sample slack.com/apps/search?q=schedule+message
SLACK_BASE_URL = "https://slack.com/apps/search"
# have to see, but potentially first search page stops at 100. That's totally fine,
# if it's outside that it's not even worth mentioning.

def lambda_handler(event, context):
    logger.debug(f"->{event}<-END")

    # events coming from API, Cron, or async invoking each other
    if 'queryStringParameters' in event:
        action = 'api'
    else:
        action = event.get("action")

    if action == 'api':
        return api(event)
    elif action == "scrape":
        keyword = event.get("keyword")
        logger.info(f'[*] scraping Slack search for term: "{keyword}"')
        check_keyword(event, keyword)
    elif action == "cron":
        keyword_docs = get_all_keyword_docs()
        num_docs = len(keyword_docs)
        logger.info('Running {} keyword searches', num_docs)
        if num_docs < 50:
            small_batch = True
        else:
            small_batch = False

        print(keyword_docs)
        for k in keyword_docs:
            k["action"] = "scrape"
            # #TODO: adjust the App Id setting to be a list so i can handle multiple in the future
            k["apps"] = [k["app_id"]]
            # if i want to run and update data without annoying anyone i can leave it off
            if event.get("send_notification"):
                k["send_notification"] = True
            invoke_individual_run(k, small_batch=small_batch)

    elif action == "scrape_dynamo":
        query_term = event.get("query")
        logger.info(f'[*] scraping Slack search for term: "{query_term}"')
        check_keyword(event, query_term, use_dynamo=True)
    elif action == "cron_dynamo":
        # for each term, kick off a scraper - scaling, do this last
        query_requests = get_query_requests_to_check()
        logger.info("Running {} queries", len(query_requests))

        # TODO: better handled with a state machine that limits concurrency, but for now keep it simple
        if len(query_requests) < 50:
            small_batch = True
        else:
            small_batch = False

        for qr in query_requests:
            qr["action"] = "scrape"
            # #TODO: adjust the App Id setting to be a list so i can handle multiple in the future
            qr["apps"] = [qr["appId"]]
            # if i want to run and update data without annoying anyone i can leave it off
            if event.get("send_notification"):
                qr["send_notification"] = True
            invoke_individual_run(qr, small_batch=small_batch)
    else:
        logger.error("[!] idk what to do with this event it is not expected")

def get_all_keyword_docs():
    # TODO: don't worry about efficiency for now, grab the whole thing and i'll figure out later if it needs less
    keyword_list = []
    if os.environ.get("LOCAL"):
        logger.debug("returning mock keyword docs")
        keyword_list = [
            {'ref': Ref('289109122272461316', 'keywords'), 'ts': 1611974794560000, 'data': {'keyword': 'recurring message', 'app_id': 'AK7KWDFU3', 'slack_webhook': 'https://fake-webhook.com', 'rank_data': [{'date': '2021-01-26', 'rank': 4, 'total_results': 13}, {'date': '2021-01-24', 'rank': 6, 'total_results': 13}, {'date': '2021-01-22', 'rank': 8, 'total_results': 13}]}},
            {
                "ts": 1613230833160000,
                "data": {
                    "keyword": "scheduled message",
                    "app_id": "AK7KWDFU3",
                    "slack_webhook": "https://hooks.slack.com/services/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",
                    "rank_data": [],
                },
                "permissions": {
                    "read": Ref(
                        '290425396619379203',
                        'users'
                    ),
                    "write": Ref(
                        '290425396619379203',
                        'users'
                    ),
                },
                "keyword": "scheduled message",
                "app_id": "AK7KWDFU3",
                "slack_webhook": "https://hooks.slack.com/services/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",
                "rank_data": [],
                "ref": Ref('290426174204543494', 'keywords'),
            }    
        ]
    else:
        index_name = 'all_keywords'
        adminClient = FaunaClient(secret=FAUNA_SECRET)
        res = adminClient.query(q.map_(lambda x: q.get(x), q.paginate(q.match(q.index(index_name)))))
        keyword_list = res['data']


    # clean up & adjust the items so it's top level instead of nestled under 'data'
    for keyword in keyword_list:
        for k,v in keyword['data'].items():
            keyword[k] = v
    
        # certain things like Ref aren't json-able, adjust or remove if not needed
        keyword['ref_id'] = keyword['ref'].id()
        del keyword['ref']
        try:
            del keyword['permissions']
        except KeyError:
            pass


    return keyword_list

def update_rank_data(doc, new_rank_data):
    del new_rank_data['app_id']
    new_rank_data['date'] = UTC_DATE
    old_data = doc['data']
    update_data = {
        'rank_data': [new_rank_data]
    }

    # TODO: does any fancy sorting need to happen here? if i kep adding on the end it should stay in order of date
    if 'rank_data' in old_data:
        update_data['rank_data'] = old_data['rank_data'] + [new_rank_data]

    if os.environ.get("LOCAL"):
        logger.debug("update mock keyword data: {}", update_data)
    else:
        adminClient = FaunaClient(secret=FAUNA_SECRET)
        res = adminClient.query(q.update(q.ref(q.collection(KEYWORD_COLLECTION), doc['ref_id']), {"data": update_data}))
        logger.info('Resp: {}', res)


def get_table_client():
    if os.environ.get("LOCAL"):
        return MagicMock(name='MockDynamoDB')
    else:
        dynamodb = boto3.resource("dynamodb")
        return dynamodb.Table(DATA_TABLE_NAME)


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
    queries_url = os.environ["SHEETY_URL"]
    headers = {"Authorization": f'Bearer {os.environ["SHEETY_BEARER_TOKEN"]}'}
    resp = requests.get(queries_url, headers=headers)
    if resp.status_code == 200:
        data = resp.json()
        return data["queries"]
    else:
        logger.error("Failed fetching from sheety - {}:{}", resp.status_code, resp.text)
        raise ValueError("Could not get queries to run from Google Sheet")


def invoke_individual_run(k, small_batch=False):
    # until i have a lot, there's not really a point to farm out the work, it's just good practice
    try:
        payload = json.dumps(k)
    except Exception as e:
        logger.error('Bad json event: {}', k)
        raise

    logger.debug("Invoke for keyword: {}", payload)
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


def parse_search_data(page_content, app_ids):
    soup = BeautifulSoup(page_content, "html.parser")
    app_rows = soup.select(".app_row")
    num_apps = len(app_rows)
    logger.info(f"Found {num_apps} app results for search term")

    results = []
    # app data gets saved in storage
    search_data = []
    for r in app_rows:
        curr_id = r.attrs.get("data-app-id")
        # TODO: brittle as hell
        pretty_name = r.select('.media_list_title')[0].text.replace('\n', '').strip()
        pretty_tagline = r.select('.media_list_subtitle')[0].text.replace('\n', '').strip() 
        search_rank = int(r.attrs.get("data-position"))
        search_data.append({
            "app_name": r.attrs.get('data-app-name'), 
            "title": pretty_name,
            'tagline': pretty_tagline,
            'app_rank': search_rank,
            'app_id': curr_id,
            'slack_owned': r.attrs.get('data-app-is-slack-owned')
        })

        if curr_id in app_ids:
            print(curr_id)
            results.append(
                {"app_id": curr_id, "rank": search_rank, "total_results": num_apps}
            )
            app_ids.remove(curr_id)

    # handle ones not found on page
    for not_found in app_ids:
        results.append({"app_id": not_found, "rank": -1, "total_results": num_apps})

    return results, search_data


def check_keyword(event, query_term, use_dynamo=False):
    app_ids = event.get("apps")
    page_content = fetch_webpage(SLACK_BASE_URL, {"q": query_term})
    # at 128mb, parsing a full page takes 10s
    results, search_data = parse_search_data(page_content, app_ids)
    try:
        # TODO: start with just saving page content, would be smart to have a schema in future
        # for just the app data that matters
        if use_dynamo:
            save_search_data(query_term, search_data, use_dynamo=use_dynamo)
        else:
            # TODO: only supports one right now, we'll see if multiple is ever needed
            new_rank_data = deepcopy(results[0])
            update_rank_data(event, new_rank_data)
    except Exception as e:
        traceback.print_exc()
        logger.error("Ruh roh raggy: {}. Didnt save but keep running", e)

    if event.get("send_notification"):
        # don't spam myself
        send_term_notification(event, query_term, results)
    else:
        logger.info("Not sending notification intentionally")


def save_search_data(query_term, search_data):
    # does it matter if multiple have same term? it's repeated work, but results should be same. Not a big deal.
    # use utc so I don't have to care about timezones ever
        new_item = {PARTITION_KEY: query_term, SORT_KEY: UTC_DATE}
        logger.info("item without search_data: {}", new_item)
        new_item["search_data"] = search_data
        resp = get_table_client().put_item(
            Item=new_item
        )
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
    if event.get("appMappings"):
        try:
            mappings = event.get("appMappings").split(",")
            for mapping in mappings:
                app_id, name = mapping.split(":")
                app_name_map[app_id] = name
        except Exception as e:
            bad_map_formatting = True
            traceback.print_exc()
            logger.error(
                "Ruh roh raggy - Mapping format was messsed up so sending only as ids: {}",
                e,
            )

    msg = f"*Search ranks for query term `{query_term}`:*\n"
    for r in results:
        rank_display = r['rank']
        if rank_display == -1:
            rank_display = "Not found in search"
        msg += f'\n>{app_name_map.get(r["app_id"], r["app_id"])}: {rank_display}'
        if r.get("total_results"):
            msg += f'/{r["total_results"]}'
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": msg}}]
    if bad_map_formatting:
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "_:warning: Your app mapping format is incorrect, so only able to display App Id_",
                    }
                ],
            }
        )
    data = {"text": "Updated keyword ranks for your apps.", "blocks": blocks}
    logger.debug(json.dumps(data))
    # sheety used 'slackWebhookUrl'
    if not os.environ.get("LOCAL") and event.get("slack_webhook"):
        resp = requests.post(event.get("slack_webhook"), json=data)
        logger.info("{}: {}", resp.status_code, resp.text)


def api(event):
    # TODO: this job is decently slow. Simple solution is to accept a ref id, then you pull that item and run the job.
    # DOn't return anything but a 200 that you accepted the work
    logger.debug("API not implemented")
    # query_term = event['queryStringParameters'].get('q')
    # # if no app_id, just return the whole search item
    # app_id = event['queryStringParameters'].get('app_id')
    # historical = event['queryStringParameters'].get('historical', False)

    # if not query_term:
    #     return {
    #         'statusCode': 400,
    #         'body': 'Need a keyword'
    #     }


    # table = get_table_client()
    # if historical:
    #     # pull multiple days of data for the keyword
    #     pass
    # else:
    #     # check db for today, else run fetch, then return
    #     utc_date = str(datetime.utcnow().date())
    #     key = ={
    #         PARTITION_KEY: query_term,
    #         SORT_KEY: utc_date
    #     }
    #     resp = table.get_item(Key=key)
    #     if 'Item' in resp:
    #         logger.debug("found item with key {}", key)

    #         if app_id:
    #             # TODO: after i fix how i store the data
    #             body = {
    #                 'app_id': app_id,
    #                 'date': utc_date,
    #                 'rank': 1
    #             }
    #         else:
    #            body = json.dumps(resp['Item'])

    #         return {
    #             'statusCode': 200,
    #             'body': json.dumps(body)
    #         }
    #     else:
            
    #         # it can take up to 10 seconds to do this with low memory lambdas, synchronous makes very little sense
    #   #  kick off job and return


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