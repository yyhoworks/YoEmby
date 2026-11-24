import threading
import time
from helper import utils
from ce_opt import config as ce_config # [CE-OPT] Lazy TTL avoids permanent 5Hz polling thread

CacheLock = threading.Lock()
CacheByPlaySessionId = {}
CacheByHTTPRequest = {}
Counter = 5
_LastTouch = 0.0 # [CE-OPT] Monotonic timestamp for lazy 1s TTL expiration

def _expire_if_stale():
    global CacheByPlaySessionId, CacheByHTTPRequest
    if CacheByHTTPRequest and (time.monotonic() - _LastTouch) > 1.0:
        CacheByPlaySessionId = {}
        CacheByHTTPRequest = {}

def get(HTTPRequest):
    global Counter, _LastTouch

    with utils.SafeLock(CacheLock):
        if ce_config.is_enabled("ce_lazy_httpcache"): # [CE-OPT] Lazy expire on access
            _expire_if_stale()
        if HTTPRequest in CacheByHTTPRequest:
            Counter = 5 # Reset Timer on http requests
            _LastTouch = time.monotonic()
            return CacheByHTTPRequest[HTTPRequest]

    return ""

def add(MetaData, Response):
    global Counter, _LastTouch

    with utils.SafeLock(CacheLock):
        if ce_config.is_enabled("ce_lazy_httpcache"): # [CE-OPT] Lazy expire on write
            _expire_if_stale()
        Counter = 5 # Reset Timer on http requests
        _LastTouch = time.monotonic()
        CacheByPlaySessionId[MetaData['PlaySessionId']] = MetaData['Payload']
        CacheByHTTPRequest[MetaData['Payload']] = (MetaData, Response)

def delete(PlaySessionId):
    with utils.SafeLock(CacheLock):
        if PlaySessionId in CacheByPlaySessionId:
            del CacheByHTTPRequest[CacheByPlaySessionId[PlaySessionId]]
            del CacheByPlaySessionId[PlaySessionId]

# Reset cache after 1 second
def clear():
    global CacheByPlaySessionId
    global CacheByHTTPRequest
    global Counter

    if ce_config.is_enabled("ce_lazy_httpcache"): # [CE-OPT] Exit polling thread immediately when lazy TTL is active
        return

    while True:
        while Counter:
            if utils.sleep(0.2):
                return

            Counter -= 1

        with utils.SafeLock(CacheLock):
            Counter = 5
            CacheByPlaySessionId = {}
            CacheByHTTPRequest = {}
