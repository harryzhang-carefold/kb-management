"""Strict recovery for SDK page-boundary checks, with the same first cache key."""
import asyncio
from . import index_recovery

async def check(classic,title,page_text,model=None,logger=None):
    prompt = classic._SYSTEM_HARDENING + f"""
    You will be given the current section title and the current page_text.
    Your job is to check if the current section starts in the beginning of the given page_text.
    If there are other contents before the current section title, then the current section does not start in the beginning of the given page_text.
    If the current section title is the first content in the given page_text, then the current section starts in the beginning of the given page_text.

    Note: do fuzzy matching, ignore any space inconsistency in the page_text.

    The given section title is {title}.
    The given page_text is:
    {classic._secure_doc_text(page_text)}

    reply format:
    {{
        "thinking": <why do you think the section appears or starts in the page_text>
        "start_begin": "yes or no" (yes if the section starts in the beginning of the page_text, no otherwise)
    }}
    Directly return the final JSON structure. Do not output anything else."""

    def validate(raw):
        value=classic.extract_json(raw)
        if not isinstance(value,dict) or value.get('start_begin') not in ['yes','no']:
            raise ValueError('Page boundary returned invalid JSON or decision')
        return value['start_begin']
    return await index_recovery.run_async(lambda note:classic.llm_acompletion(model=model,prompt=prompt+note),validate,'page boundary check')

async def check_all(classic,structure,page_list,model=None,logger=None):
    result=[dict(item) for item in structure]
    selected=[]
    for item in result:
        page=item.get('physical_index')
        if page is None:item['appear_start']='no';continue
        if type(page) is not int or not 1<=page<=len(page_list):
            raise ValueError('Page boundary has invalid physical page')
        selected.append(item)
    # Gather must propagate exhausted checks; an exception is not a "no".
    values=await asyncio.gather(*(check(classic,item['title'],page_list[item['physical_index']-1][0],model,logger) for item in selected))
    for item,value in zip(selected,values):item['appear_start']=value
    return result
