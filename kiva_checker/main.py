from string import Template
import os
import requests
import boto3

def main(event, context):
    try:
        SNS_TOPIC_ARN = os.environ["SNS_TOPIC_ARN"]
        ISO_CODES = os.environ["ISO_CODES"]
    except KeyError as e:
        print("[!] failed getting necessary env variable -> %s" % e)
        return
    headers = {}
    kiva_url = "https://api.kivaws.org/graphql?"
    # iso_codes = "BD,BJ,BT,BZ,CA,CI,GU,LA,NA,NG,PA,PG,PR,SS,TH,TR,VI,ZA"
    # iso_codes = "US, KE"
    countries = ISO_CODES.split(",")
    query_template = Template("""
{
  lend {
    loans (filters: {country: $countries}, limit: 4) {
      totalCount
      values {
        name
        loanAmount
        geocode {
          country {
            isoCode
            name
          }
        }
      }
    }
  }
}

    """)

    query = query_template.substitute(countries=countries).replace("'", '"')
    r = requests.post(kiva_url, json={"query": query}, headers=headers)
    # empty response {'data': {'lend': {'loans': {'totalCount': 0, 'values': []}}}}
    # if it finds totalCount > 0, it publishes to SNS topic? send me email?

    outcome_msg = "None found, drat"
    if r.status_code == 200:
        data = r.json()
        print(data)
        try:
            total_count = data["data"]["lend"]["loans"]["totalCount"]
        except KeyError as e:
            outcome_msg = "[!] failed with KeyError %s" % e
            return outcome_msg

        if total_count > 0:
            # https://www.kiva.org/lend?country=BD,BT,BZ,CA,CL,GU,LA,SS,VI,ZA
            print("Found loans, notify Kevin")
            base_url = 'https://www.kiva.org/lend?country='
            outcome_msg = f'Loans found in these countries {base_url}{ISO_CODES}'
            sns = boto3.client('sns')
            response = sns.publish(
                TopicArn=SNS_TOPIC_ARN,    
                Message=outcome_msg,    
            )
        else:
            outcome_msg = "None found, drat"
    else:
        outcome_msg = "[!] request failed with status %d" % r.status_code
        
    print(outcome_msg)
    return outcome_msg

if __name__ == "__main__":
    main(None, None)
