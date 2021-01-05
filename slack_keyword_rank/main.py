import sys
import urllib.parse
from datetime import datetime

import requests
from bs4 import BeautifulSoup

# sample slack.com/apps/search?q=schedule+message
SLACK_BASE_URL = 'https://slack.com/apps/search'
# have to see, but potentially first search page stops at 100. That's totally fine,
# if it's outside that it's not even worth mentioning.

def lambda_handler(event, context):
    if event.get('action') == 'scrape':
        query_term = event.get('query')
        print(f'scraping Slack search for term: "{query_term}"')
        check_term(query_term)
    else:
        # not a scraper, so it's the control lambda
        # for each term, kick off a scraper - scaling, do this last
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

def check_term(query_term):
    page_content = fetch_webpage(SLACK_BASE_URL, {'q': query_term})
    # with open('test.html', 'r') as f:
    #     page_content = f.read()
    soup = BeautifulSoup(page_content, 'html.parser')
    scrape_date = str(datetime.utcnow()) + " UTC"
    
    app_rows = soup.select('.app_row')
    print(f'Found {len(app_rows)} app results for search term')
    # print(app_rows)
    # with open('test.html', 'w') as f:
    #     f.write(soup.prettify())

if __name__ == '__main__':
    query_term = sys.argv[1]
    event = {'action': 'scrape', 'query': query_term }
    lambda_handler(event, None)