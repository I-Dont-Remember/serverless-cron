from cProfile import run
from threading import local
import bs4
import csv

# process: 
# - for each income level, run the website & copy the table of region data
# Run the script to extract that into a CSV that can be used in sheets
def convert_str_pct_to_float(str_pct):
    ret = str_pct.replace('%', 'e-2')
    ret = float(ret)
    # ret = ret / 100.0
    return ret
    
def run_benchmark_scrape(benchmark_num):
    local_file = f'./html_pages/{benchmark_num}.html'
    output_file = f'./output_csvs/{benchmark_num}.csv'
    with open(local_file, 'r') as lf:
        soup = bs4.BeautifulSoup(lf.read(), 'html.parser')

    state_rows = soup.find_all('div', 'c-table__body')

    state_data = []
    for row in state_rows:
        cells = row.find_all('div', 'c-table__td')
        state_data.append({
            'state': cells[0].get_text(),
            f'{benchmark_num}_pay': cells[1].get_text().replace('USD', '').replace(',', ''),
            f'{benchmark_num}_tax_pct': convert_str_pct_to_float(cells[2].get_text()),
            f'{benchmark_num}_rank': cells[3].get_text()
        })

    print(f'Found data for {len(state_data)} regions...', state_data[:1])
    with open(output_file, 'w') as fp:
        field_names = ['state',  f'{benchmark_num}_pay', f'{benchmark_num}_tax_pct', f'{benchmark_num}_rank']
        writer = csv.DictWriter(fp, field_names)
        writer.writerows(state_data)
    return state_data

salary_benchmarks = ['50k', '75k', '100k', '125k', '150k', '200k', '250k', '300k']

benchmark_data_rows = []
for bmark in salary_benchmarks:
    print(f'### Running for {bmark}...')
    benchmark_data_rows.extend(run_benchmark_scrape(bmark))
    print('=== completed all pages successfully===')

print(len(benchmark_data_rows))
d = {}
for r in benchmark_data_rows:
    try:
        curr_state_data = d[r['state']]
        for k,v in r.items():
            if k != 'state':
                curr_state_data[k] = v
    except KeyError:
        d[r['state']] = r

for v in d.values():
    print(v)
    break
## TODO: do all the CSV concatenation & stuff autoamted rather than by hand

with open('output_csvs/full_data_set.csv', 'w') as fp:
    field_names = d['Florida'].keys()
    writer = csv.DictWriter(fp, field_names)
    writer.writeheader()
    writer.writerows(d.values())