# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     jetkai.py
   Description :   Jetkai代理源
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


class JetkaiFetcher(BaseFetcher):
    """Jetkai proxy-list https://github.com/jetkai/proxy-list"""

    name = "jetkai"
    url = "https://github.com/jetkai/proxy-list"

    def fetch(self):
        raw_url = "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-http.txt"
        r = WebRequest().get(raw_url, timeout=10)
        for proxy in self.yieldUniqueProxies(self.parseProxiesFromText(r.text)):
            yield proxy


if __name__ == '__main__':
    for proxy in JetkaiFetcher().fetch():
        print(proxy)
