# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     thespeedx.py
   Description :   TheSpeedX代理源
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


class TheSpeedXFetcher(BaseFetcher):
    """TheSpeedX PROXY-List https://github.com/TheSpeedX/PROXY-List"""

    name = "thespeedx"
    url = "https://github.com/TheSpeedX/PROXY-List"

    def fetch(self):
        raw_url = "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt"
        r = WebRequest().get(raw_url, timeout=10)
        for proxy in self.yieldUniqueProxies(self.parseProxiesFromText(r.text)):
            yield proxy


if __name__ == '__main__':
    for proxy in TheSpeedXFetcher().fetch():
        print(proxy)
