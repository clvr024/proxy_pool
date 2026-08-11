# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     monosans.py
   Description :   Monosans代理源
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


class MonosansFetcher(BaseFetcher):
    """Monosans proxy-list https://github.com/monosans/proxy-list"""

    name = "monosans"
    url = "https://github.com/monosans/proxy-list"

    def fetch(self):
        raw_url = "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt"
        r = WebRequest().get(raw_url, timeout=10)
        for proxy in self.yieldUniqueProxies(self.parseProxiesFromText(r.text)):
            yield proxy


if __name__ == '__main__':
    for proxy in MonosansFetcher().fetch():
        print(proxy)
