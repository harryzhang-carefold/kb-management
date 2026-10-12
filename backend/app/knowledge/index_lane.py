"""Limit the pinned SDK's Classic indexing calls to one background request."""
import asyncio
import threading
import time
import hashlib
import json
from contextvars import ContextVar

gate=threading.Semaphore(1)
lock=threading.Lock()
foreground=0
installed=False
progress=None
completed=0
cached=0
visualizer=ContextVar('index_page_images',default=None)
last_key=ContextVar('index_completion_key',default=None)
recovery_progress=None

def request(args,kwargs):
    images=visualizer.get()
    if images is None:return args,kwargs
    if 'prompt' in kwargs:return args,kwargs|{'prompt':images(kwargs['prompt'])}
    if len(args)>1:return (args[0],images(args[1]),*args[2:]),kwargs
    return args,kwargs

def report(hit=False):
    global completed,cached
    if hit:cached+=1
    else:completed+=1
    if progress:progress(completed,cached)

def cache_key(args,kwargs):
    from pageindex.utils import _llm_backend
    payload=json.dumps([args,kwargs,_llm_backend.get()],sort_keys=True,ensure_ascii=False,default=str)
    return hashlib.sha256(payload.encode()).hexdigest()

def cached_result(key):
    from . import store
    seen=set()
    for _ in range(4):
        if key in seen:return None
        seen.add(key);rejected=store.get('index_rejected',key,{})
        if not rejected.get('rejected'):break
        if not rejected.get('replacement'):return None
        key=rejected['replacement']
    else:return None
    result=store.get('index_completion',key)
    if result is not None:
        report(True)
        return tuple(result['value']) if result['tuple'] else result['value']

def save_result(key,value):
    from . import store
    if value:
        store.put('index_completion',key,{'value':value,'tuple':isinstance(value,tuple)})
        store.put('index_rejected',key,{'rejected':False})
    report()
    return value

def reject(key):
    from . import store
    if key:store.put('index_rejected',key,{'rejected':True})

def recovered(keys,replacement):
    from . import store
    if replacement:
        for key in keys:
            if key and key!=replacement:store.put('index_rejected',key,{'rejected':True,'replacement':replacement})

async def acquire_gate():
    # Waiting must not consume threads from the model client's worker pool.
    while not gate.acquire(blocking=False):await asyncio.sleep(.05)

def enter():
    global foreground
    with lock: foreground+=1

def leave():
    global foreground
    with lock: foreground=max(0,foreground-1)

def install():
    global installed
    if installed:return
    from pageindex import utils
    sync,async_=utils.llm_completion,utils.llm_acompletion
    def limited(*args,**kwargs):
        with gate:
            while foreground:time.sleep(.15)
            args,kwargs=request(args,kwargs)
            key=cache_key(args,kwargs)
            last_key.set(key)
            hit=cached_result(key)
            if hit is not None:return hit
            return save_result(key,sync(*args,**kwargs))
    async def limited_async(*args,**kwargs):
        # LiteLLM also needs this loop's worker pool. Blocking every worker
        # on gate.acquire deadlocks the first model call when many nodes verify.
        await acquire_gate()
        try:
            while foreground:await asyncio.sleep(.15)
            args,kwargs=request(args,kwargs)
            key=cache_key(args,kwargs)
            last_key.set(key)
            hit=cached_result(key)
            if hit is not None:return hit
            return save_result(key,await async_(*args,**kwargs))
        finally:gate.release()
    utils.llm_completion=limited;utils.llm_acompletion=limited_async
    # Classic imports utility names by value. The pinned seam is explicit.
    from pageindex import page_index_classic
    from . import pageindex_compat
    pageindex_compat.install(page_index_classic)
    page_index_classic.llm_completion=limited;page_index_classic.llm_acompletion=limited_async
    installed=True
