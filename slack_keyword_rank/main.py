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

app_name_map = {
    'AK7KWDFU3': 'Nightowl'
}

LAMBDA_NAME = 'personal-cron-dev-slack_keyword_rank'
DATA_TABLE_NAME = 'slack-keyword-searches'
PARTITION_KEY = 'query_term'
SORT_KEY = 'date'

SLACK_WEBHOOK_URL = os.environ['SLACK_WEBHOOK_URL']

# sample slack.com/apps/search?q=schedule+message
SLACK_BASE_URL = 'https://slack.com/apps/search'
# have to see, but potentially first search page stops at 100. That's totally fine,
# if it's outside that it's not even worth mentioning.

def lambda_handler(event, context):
    logger.debug(f'->{event}<-END')
    action = event.get('action')
    if action == 'scrape':
        query_term = event.get('query')
        logger.info(f'scraping Slack search for term: "{query_term}"')
        check_term(event, query_term)
    elif action == 'cron':
        # for each term, kick off a scraper - scaling, do this last
        query_requests = get_query_requests_to_check()
        
        # TODO: better handled with a state machine that limits concurrency, but for now keep it simple
        for qr in query_requests:
            qr['action'] = 'scrape'
            if event.get('send_notification'):
                qr['send_notification'] = True
            invoke_individual_run(qr)
    else:
        logger.error('[!] idk what to do with this event it is not expected')

def get_query_requests_to_check():
    # eventually this will be from a DB or Google Sheets, for now just do system variables
    # json str from environment variable
    jstr = os.environ['query_requests']
    return json.loads(jstr)


def invoke_individual_run(qr):
    payload = json.dumps(qr)
    logger.debug('Invoke for query: {}', payload)
    if os.environ.get('LOCAL'):
        logger.debug('fake invocation')
        # lambda unloads the json event for us
        lambda_handler(json.loads(payload), None)
    else:
        lambda_client = boto3.client("lambda")
        response = lambda_client.invoke(
            FunctionName=LAMBDA_NAME,
            InvocationType='Event',
            Payload=payload,
        )
        logger.info(response)


def fetch_webpage(url, params):
    if os.environ.get('LOCAL'):
        with open('slack_keyword_rank/test.html', 'r') as f:
                return f.read()
    else:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 6.2; Win64; x64; rv:16.0.1) Gecko/20121011 Firefox/16.0.1"
        }
        resp = requests.get(url, headers=headers, params=params)
        logger.info(f"[*] fetched data from url: {resp.url}")
        if resp.status_code != 200:
            logger.error(f"[!] {resp.status_code}: {resp.content}")
            raise ValueError('FAIL')
        
        # with open('test.html', 'w') as f:
        #     f.write(soup.prettify())
        return resp.content

def check_term(event, query_term):
    app_ids = event.get('apps')
    page_content = fetch_webpage(SLACK_BASE_URL, {'q': query_term})
    soup = BeautifulSoup(page_content, 'html.parser')    
    app_rows = soup.select('.app_row')
    num_apps = len(app_rows)
    logger.info(f'Found {num_apps} app results for search term')

    results = []
    for row in app_rows:
        curr_id = row.attrs.get('data-app-id')
        if curr_id in app_ids:
            print(curr_id)
            rank = row.attrs.get('data-position')
            results.append({'app_id': curr_id, 'search_rank': rank, 'total_results': num_apps})
            app_ids.remove(curr_id)
    
    # handle ones not found on page
    for not_found in app_ids:
        results.append({'app_id': not_found, 'search_rank': 'Not found in search'})

    try:
        # TODO: start with just saving page content, would be smart to have a schema in future
        # for just the app data that matters
        save_search_data(query_term, app_rows)
    except Exception as e:
        traceback.print_exc()
        logger.error('Ruh roh raggy: {}. Didnt save but keep running', e)

    if event.get('send_notification'):
        # don't spam myself
        send_term_notification(event, query_term, results)

def save_search_data(query_term, data):
    if os.environ.get('LOCAL'):
        logger.debug('saving data boii')
    else:    
        # save the page content for now, then switch it to json in the future
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table(DATA_TABLE_NAME)

        # use utc so I don't have to care about timezones ever
        date = str(datetime.utcnow().date())
        item = {
            PARTITION_KEY: query_term,
            SORT_KEY: date,
            'data': data
        }
        resp = table.put_item(Item=item)
        logger.info(resp)


def send_term_notification(event, query_term, results):
    if not results:
        logger.warn("No results, nothing to send. Not really an error.")
        return None

    # when i want to scale out to sending for multiple workspaces
    # if event.get('slack_webhook'):
    #     raise ValueError('[!] cant send a message without a webhook')

    msg = f'*Search ranks for query term `{}`:*\n'
    for r in results:
        msg += f'\n>{app_name_map.get(r["app_id"], r["app_id"])}: {r["search_rank"]}'
        if r.get('total_results'):
            msg += f'/{r["total_results"]}'
    blocks = [query_term
        {
            'type': 'section',
            'text': {
                'type': 'mrkdwn',
                'text': msg
            }
        }
    ]
    data = {
        'text': 'Updated keyword ranks for your apps.',
        'blocks': blocks
    }
    logger.debug(json.dumps(data))
    if not os.environ.get('LOCAL'):
        resp = requests.post(SLACK_WEBHOOK_URL, json=data)
        logger.info('{}: {}', resp.status_code, resp.text)


if __name__ == '__main__':
    os.environ['LOCAL'] = 'true'
    # cron control run
    query_requests = [
        {
            'query': 'schedule message',
            'apps': ['AK7KWDFU3']
        },
        {
            'query': 'recurring message',
            'apps': ['AK7KWDFU3']
        }
    ]
    os.environ['query_requests'] = json.dumps(query_requests)

    event = {
        'action': 'cron'
    }
    # single event
    # query_term = 'abc'# sys.argv[1]
    # event = {'action': 'scrape', 'query': query_term , 'apps': ['AK7KWDFU3']}
    lambda_handler(event, None)