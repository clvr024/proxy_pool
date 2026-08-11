# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     clarketm.py
   Description :   Clarketm代理源
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


class ClarketmFetcher(BaseFetcher):
    """Clarketm proxy-list https://github.com/clarketm/proxy-list"""

    name = "clarketm"
    url = "https://github.com/clarketm/proxy-list"

    def fetch(self):
        raw_url = "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt"
        r = WebRequest().get(raw_url, timeout=10)
        for proxy in self.yieldUniqueProxies(self.parseProxiesFromText(r.text)):
            yield proxy


if __name__ == '__main__':
    for proxy in ClarketmFetcher().fetch():
        print(proxy)
