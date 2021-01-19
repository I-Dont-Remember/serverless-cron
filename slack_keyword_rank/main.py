import sys
import os
import json
import urllib.parse
from datetime import datetime

import requests
from bs4 import BeautifulSoup

app_name_map = {
    'AK7KWDFU3': 'Nightowl'
}


SLACK_WEBHOOK_URL = 'https://hooks.slack.com/services/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'

# sample slack.com/apps/search?q=schedule+message
SLACK_BASE_URL = 'https://slack.com/apps/search'
# have to see, but potentially first search page stops at 100. That's totally fine,
# if it's outside that it's not even worth mentioning.

def lambda_handler(event, context):
    print(f'> {event}\n<-END')
    if event.get('action') == 'scrape':
        query_term = event.get('query')
        print(f'scraping Slack search for term: "{query_term}"')
        check_term(event, query_term)
    else:
        # not a scraper, so it's the control lambda
        # for each term, kick off a scraper - scaling, do this last
        pass

# def get_terms():
#     # eventually this will be from a DB or Google Sheets, for now just do system variables

#     # json str from environment variable
#     jstr = os.environ[]


def invoke_individual_run():
    # given event {'action': 'scrape', 'query': query_term }  ? TODO: and app?
    pass

def fetch_webpage(url, params):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 6.2; Win64; x64; rv:16.0.1) Gecko/20121011 Firefox/16.0.1"
    }
    resp = requests.get(url, headers=headers, params=params)
    print(f"[*] fetching data from url: {resp.url}")
    if resp.status_code != 200:
        print(f"[!] {resp.status_code}: {resp.content}")
        print("WTF")
        raise SystemExit
    return resp.content

def check_term(event, query_term):
    app_ids = event.get('app_ids')
    # page_content = fetch_webpage(SLACK_BASE_URL, {'q': query_term})
    with open('slack_keyword_rank/test.html', 'r') as f:
        page_content = f.read()
    soup = BeautifulSoup(page_content, 'html.parser')
    scrape_date = str(datetime.utcnow()) + " UTC"
    
    app_rows = soup.select('.app_row')
    print(f'Found {len(app_rows)} app results for search term')

    results = []
    for row in app_rows:
        curr_id = row.attrs.get('data-app-id')
        if curr_id in app_ids:
            rank = row.attrs.get('data-position')
            results.append({'app_id': curr_id, 'search_rank': rank})

    send_term_notification(event, results)

# given a list of keywords+apps, create a single message
# Only send it to Happybara workspace for now


    # TODO: find app rank


    # print(app_rows)
    # with open('test.html', 'w') as f:
    #     f.write(soup.prettify())

def send_term_notification(event, results):
    if not results:
        print("No results, nothing to send. Not really an error.")
        return None

    # when i want to scale out to sending for multiple workspaces
    # if event.get('slack_webhook'):
    #     raise ValueError('[!] cant send a message without a webhook')

    msg = '*Search ranks for query term `abc`:*\n'
    for r in results:
        msg += f'\n{app_name_map[r["app_id"]]}: {r["search_rank"]}'
    blocks = [
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
    print(json.dumps(data))
    resp = requests.post(SLACK_WEBHOOK_URL, json=data)
    print(resp.status_code)
    print(resp.text)


if __name__ == '__main__':

    # cron control run
    # query_terms = [
    #     {
    #         'query': 'scheduled message',
    #         'app': 'ANQDDNT4J' 
    #     }
    # ]
    # os.environ[QUERY_TERMS] = json.dumps(query_terms)

    # single event
    query_term = 'abc'# sys.argv[1]
    event = {'action': 'scrape', 'query': query_term , 'app_ids': ['AK7KWDFU3']}
    lambda_handler(event, None)