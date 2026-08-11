# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     freeproxylist.py
   Description :   FreeProxyList代理源
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


class FreeProxyListFetcher(BaseFetcher):
    """FreeProxyList https://free-proxy-list.net/"""

    name = "freeproxylist"
    url = "https://free-proxy-list.net/"

    def fetch(self):
        target_url = "https://free-proxy-list.net/"
        r = WebRequest().get(target_url, timeout=10)
        for proxy in self.yieldUniqueProxies(self.parseProxiesFromText(r.text)):
            yield proxy


if __name__ == '__main__':
    for proxy in FreeProxyListFetcher().fetch():
        print(proxy)
