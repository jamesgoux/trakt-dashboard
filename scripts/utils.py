"""Shared utilities for Iris data pipeline scripts."""

import time
import requests


def retry_request(method, url, max_retries=3, backoff=1.0, **kwargs):
    """
    Make an HTTP request with exponential backoff retry.
    
    Args:
        method: 'get' or 'post'
        url: request URL
        max_retries: number of retries (default 3)
        backoff: initial backoff in seconds (doubles each retry)
        **kwargs: passed to requests.get/post (headers, params, json, data, timeout, etc.)
    
    Returns:
        requests.Response or None on total failure
    """
    kwargs.setdefault("timeout", 15)
    func = requests.get if method == "get" else requests.post

    for attempt in range(max_retries + 1):
        try:
            r = func(url, **kwargs)
            if r.status_code == 429:  # rate limited
                wait = backoff * (2 ** attempt)
                print(f"  Rate limited on {url}, waiting {wait}s...")
                time.sleep(wait)
                continue
            if r.status_code >= 500:  # server error, retry
                if attempt < max_retries:
                    time.sleep(backoff * (2 ** attempt))
                    continue
            return r
        except (requests.ConnectionError, requests.Timeout) as e:
            if attempt < max_retries:
                wait = backoff * (2 ** attempt)
                print(f"  Connection error on {url}, retry in {wait}s: {e}")
                time.sleep(wait)
            else:
                print(f"  Failed after {max_retries} retries: {url}")
        except Exception as e:
            print(f"  Unexpected error on {url}: {e}")
            break
    return None
