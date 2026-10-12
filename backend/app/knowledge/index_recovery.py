"""Bounded source-checked recovery; never reuse a rejected model response."""
import json
from . import index_lane

class Exhausted(ValueError):pass

def failure(key,label,attempt):
    index_lane.reject(key)
    if index_lane.recovery_progress:index_lane.recovery_progress(label,attempt)

def feedback(label,attempt):
    return '' if attempt==1 else f'\nAutomatic recovery attempt {attempt}/3 for {label}. The previous response failed validation. Return ONE complete JSON object in the requested schema. Preserve all supplied IDs and directory order; never infer unsupported pages or choose a duplicate heading without its directory context.'

def run(call,validate,label):
    rejected=[]
    for attempt in range(1,4):
        index_lane.last_key.set(None)
        response=call(feedback(label,attempt));key=index_lane.last_key.get()
        try:result=validate(response)
        except Exhausted:raise
        except (ValueError,KeyError,TypeError,json.JSONDecodeError) as exc:
            failure(key,label,attempt);rejected.append(key)
            if attempt==3:raise Exhausted(f'{label} failed after 3 automatic source-checked attempts: {exc}') from exc
        else:
            index_lane.recovered(rejected,key)
            if rejected and index_lane.recovery_progress:index_lane.recovery_progress(label,0)
            return result

async def run_async(call,validate,label):
    rejected=[]
    for attempt in range(1,4):
        index_lane.last_key.set(None)
        response=await call(feedback(label,attempt));key=index_lane.last_key.get()
        try:result=validate(response)
        except Exhausted:raise
        except (ValueError,KeyError,TypeError,json.JSONDecodeError) as exc:
            failure(key,label,attempt);rejected.append(key)
            if attempt==3:raise Exhausted(f'{label} failed after 3 automatic source-checked attempts: {exc}') from exc
        else:
            index_lane.recovered(rejected,key)
            if rejected and index_lane.recovery_progress:index_lane.recovery_progress(label,0)
            return result
