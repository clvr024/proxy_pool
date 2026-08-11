# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     proxyscrape.py
   Description :   ProxyScrape免费代理源
   Author :        JHao
   date：          2026/06/01
-------------------------------------------------
   Change Activity:
                   2026/06/01:
-------------------------------------------------
"""
__author__ = 'JHao'

from fetcher.baseFetcher import BaseFetcher
from util.webRequest import WebRequest


class ProxyScrapeFetcher(BaseFetcher):
    """ProxyScrape https://proxyscrape.com/"""

    name = "proxyscrape"
    url = "https://proxyscrape.com/"

    def fetch(self):
        api_url = "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all"
        r = WebRequest().get(api_url, timeout=10)
        for proxy in self.yieldUniqueProxies(self.parseProxiesFromText(r.text)):
            yield proxy


if __name__ == '__main__':
    for proxy in ProxyScrapeFetcher().fetch():
        print(proxy)
