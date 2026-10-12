"""Compatibility fix for PageIndex 6d23caf's missing printed-page offset.

Keep the SDK's physical-page matching and verification. Never assume an offset.
"""

import copy
import json
import re
import asyncio
from pathlib import Path


class MissingPageOffset(ValueError):
    pass


async def isolated_meta(call,*args,**kwargs):
    # SDK async metadata code calls synchronous model functions. Give each
    # invocation its own worker loop so its gate wait cannot block another
    # invocation's async model response and gate release. to_thread preserves
    # the selected backend and original-image ContextVars.
    return await asyncio.to_thread(lambda:asyncio.run(call(*args,**kwargs)))


def reference_leaf(node):
    title=re.sub(r'\s+',' ',node.get('title','')).strip().lower()
    return not node.get('nodes') and bool(re.fullmatch(
        r'(?:bibliography(?: and index of names)?|references|subject index|name index|index of names|author index|index|list of (?:boxes|figures|tables)|参考文献|文献目录|主题索引|人名索引|索引|图目录|表目录)',title))


async def refine_verified(call,node,*args,**kwargs):
    from . import index_lane
    snapshot=copy.deepcopy(node)
    start,end=snapshot.get('start_index'),snapshot.get('end_index')
    if type(start) is not int or type(end) is not int or not 1<=start<=end:
        raise ValueError('Optional refinement needs a verified physical-page range')
    try:return await call(node,*args,**kwargs)
    except Exception as exc:
        if isinstance(exc,(OSError,MemoryError)):raise
        # Optional child generation may fail after the original section has
        # passed its source checks. Keep that verified section and its range.
        node.clear();node.update(snapshot)
        if index_lane.recovery_progress:
            index_lane.recovery_progress('retained verified section: '+snapshot['title']+' ('+str(start)+'–'+str(end)+')',0,{'type':type(exc).__name__,'message':str(exc)[:2000]})
        return node


class StructureConfig:
    """Keep the SDK tree checks; page evidence is stored independently."""
    def __init__(self,loader):self.loader=loader
    def load(self,options=None):
        return self.loader.load((options or {})|{'if_add_node_summary':'no','if_add_doc_description':'no','if_add_node_text':'no'})


class PreparedText:
    """Use the validated OCR page store instead of a second PDF text parser."""
    def __init__(self,path,pages,page_count):
        if len(pages)!=page_count or any(p.get('page_index')!=i or not isinstance(p.get('markdown'),str) for i,p in enumerate(pages,1)):
            raise ValueError('Page matching needs complete ordered physical-page evidence')
        self.path=Path(path).resolve();self.text=[p['markdown'] for p in pages]
    def __call__(self,path):
        if Path(path).resolve()!=self.path:raise ValueError('Page matching evidence belongs to a different PDF')
        return list(self.text)


async def verified_titles(classic,page_list,items,start_index=1,N=None,model=None):
    """A model error must not disappear from the verification denominator."""
    indices=range(len(items)) if N is None else classic.random.sample(range(len(items)),min(N,len(items)))
    indices=list(indices)
    selected=[items[i]|{'list_index':i} for i in indices if items[i].get('physical_index') is not None]
    results=await asyncio.gather(*(classic.check_title_appearance(i,page_list,start_index,model) for i in selected))
    missing=[{'list_index':i,'answer':'no','title':items[i]['title'],'page_number':None} for i in indices if items[i].get('physical_index') is None]
    wrong=[i for i in results if i['answer']!='yes']+missing
    return (len(indices)-len(wrong))/len(indices) if indices else 0,wrong


def merge_matches(structure, matches, valid_pages):
    """Apply page positions by stable ID; preserve every original entry."""
    result = copy.deepcopy(structure)
    if not isinstance(matches, list):
        raise ValueError('Page matching must return a list')
    positions = {}
    for match in matches:
        if not isinstance(match, dict):
            continue
        ident, page = match.get('id'), match.get('physical_index')
        if type(ident) is not int or not 0 <= ident < len(result):
            continue
        if isinstance(page, str):
            marker = re.fullmatch(r'<physical_index_(\d+)>', page.strip())
            page = int(marker[1]) if marker else None
        if type(page) is not int or page not in valid_pages:
            continue
        if ident in positions and positions[ident] != page:
            raise ValueError('Conflicting physical pages for one directory entry')
        positions[ident] = page
    for ident, page in positions.items():
        if result[ident].get('physical_index') is None:
            result[ident]['physical_index'] = f'<physical_index_{page}>'
    return result

def reconcile_matches(classic,structure,matches,part_text,model=None):
    """Resolve conflicting candidates by reading each original section start.

    Never select the first candidate or infer a printed-page offset.
    """
    valid=classic._extract_chunk_marker_set(part_text)
    if not isinstance(matches,list):return merge_matches(structure,matches,valid)
    candidates={}
    for m in matches:
        if not isinstance(m,dict) or type(m.get('id')) is not int or not 0<=m['id']<len(structure):continue
        page=m.get('physical_index')
        if isinstance(page,str):
            marker=re.fullmatch(r'<physical_index_(\d+)>',page.strip());page=int(marker[1]) if marker else None
        if type(page) is int and page in valid:candidates.setdefault(m['id'],set()).add(page)
    conflicts={i:p for i,p in candidates.items() if len(p)>1 and structure[i].get('physical_index') is None}
    if sum(map(len,conflicts.values()))>12:raise ValueError('Page matching returned too many conflicting section candidates')
    resolved=[m for m in matches if not isinstance(m,dict) or m.get('id') not in conflicts]
    located=merge_matches(structure,resolved,valid)
    def source_check(title,page):
        from . import index_recovery
        marker=f'<physical_index_{page}>';parts=part_text.split(marker)
        if len(parts)<3:raise ValueError('Page matching candidate has no complete source page')
        prompt=classic._SYSTEM_HARDENING+'\nResolve a conflicting section START candidate. A contents entry, running header, caption or prose mention does NOT count. Use the original image when available. A directory can abbreviate a heading; edition versus printing is allowed only when the section type and explicit year both match the original heading. Return only JSON {"answer":"yes"} if this actual section starts here, otherwise {"answer":"no"}.\nSection title: '+classic._secure_doc_text(title)+'\nOriginal physical page '+str(page)+':\n'+classic._secure_doc_text(parts[1])
        def validate(response):
            answer=classic.extract_json(response)
            if not isinstance(answer,dict) or answer.get('answer') not in ['yes','no']:raise ValueError('Page matching candidate verification returned invalid JSON')
            return answer['answer']=='yes'
        return index_recovery.run(lambda note:classic.llm_completion(model=model,prompt=prompt+note),validate,'section start check')
    for identity,pages in conflicts.items():
        accepted=[]
        for page in sorted(pages):
            if source_check(structure[identity]['title'],page):accepted.append(page)
        if len(accepted)>1:
            # Repeated headings can both be real, e.g. a foreword subsection
            # and the book's Acknowledgments. Use directory order only after
            # independently verifying the adjacent section's original start.
            for neighbors,lower in [(located[:identity][::-1],True),(located[identity+1:],False)]:
                for neighbor in neighbors[:3]:
                    page=neighbor.get('physical_index')
                    if isinstance(page,str):
                        marker=re.fullmatch(r'<physical_index_(\d+)>',page.strip());page=int(marker[1]) if marker else None
                    if type(page) is not int or page not in valid:continue
                    if source_check(neighbor['title'],page):
                        accepted=[p for p in accepted if p>=page] if lower else [p for p in accepted if p<=page]
                        break
        if not accepted:
            # Rejected guesses in an early chunk are not missing sections.
            # Preserve this entry unresolved so later chunks can locate it.
            continue
        if len(accepted)!=1:raise ValueError(f'Page matching conflict remains for entry {identity} ({structure[identity]["title"]}), candidate physical pages {sorted(pages)}, verified candidates {accepted}')
        resolved.append({'id':identity,'physical_index':accepted[0]})
    return merge_matches(structure,resolved,valid)


def install(classic):
    if getattr(classic, '_carefold_offset_fix', False):
        return
    add_offset = classic.add_page_offset_to_toc_json
    process = classic.process_toc_with_page_numbers
    repair = classic.fix_incorrect_toc_with_retries
    meta = classic.meta_processor
    large_node = classic.process_large_node_recursively

    async def metadata(*args,**kwargs):
        return await isolated_meta(meta,*args,**kwargs)

    async def subdivide(node,*args,**kwargs):
        if reference_leaf(node):return node
        return await refine_verified(large_node,node,*args,**kwargs)

    async def title_start(item,page_list,start_index=1,model=None):
        from . import index_recovery
        page=item.get('physical_index')
        if type(page) is not int or not start_index<=page<start_index+len(page_list):
            raise ValueError('Page matching returned an invalid physical page')
        prompt=classic._SYSTEM_HARDENING+'''\nVerify a section START on this physical document page. A title listed in a
table of contents, running header, caption, or ordinary prose does NOT count.
Use the original page image when available. Ignore OCR spacing differences.
Return JSON {"answer":"yes"} only if the actual section starts here;
otherwise return {"answer":"no"}. Do not guess a printed-page offset.
Section title: '''+classic._secure_doc_text(item['title'])+'\nPage:\n'+classic._secure_doc_text(page_list[page-start_index][0])
        def validate(raw):
            response=classic.extract_json(raw)
            if not isinstance(response,dict) or response.get('answer') not in ['yes','no']:raise ValueError('Page matching verification returned invalid JSON')
            return response
        response=await index_recovery.run_async(lambda note:classic.llm_acompletion(model=model,prompt=prompt+note),validate,'section title check')
        return {'list_index':item['list_index'],'answer':response['answer'],'title':item['title'],'page_number':page}

    async def verify(page_list,list_result,start_index=1,N=None,model=None):
        return await verified_titles(classic,page_list,list_result,start_index,N,model)

    async def boundaries(structure,page_list,model=None,logger=None):
        from . import index_boundaries
        return await index_boundaries.check_all(classic,structure,page_list,model,logger)

    async def checked_repair(*args,**kwargs):
        import inspect
        from . import index_source_repair
        params=inspect.signature(repair).bind(*args,**kwargs);params.apply_defaults();p=params.arguments
        result,incorrect=await repair(*args,**kwargs)
        # The SDK catches item exceptions and can drop them. Recheck every
        # initially failed item so a skipped error cannot count as repaired.
        remaining={i['list_index']:i for i in incorrect}
        for item in p['incorrect_results']:
            i=item['list_index'];check=result[i]|{'list_index':i}
            try:verified=await classic.check_title_appearance(check,p['page_list'],p['start_index'],p['model'])
            except Exception:remaining[i]=item;continue
            if verified['answer']!='yes':remaining[i]=item
        if remaining:
            result,incorrect=await index_source_repair.repair(classic,result,p['page_list'],list(remaining.values()),p['start_index'],p['model'])
        else:incorrect=[]
        if incorrect:raise ValueError('Page matching still failed after original-heading repair: '+str([{'title':i['title'],'physical_index':result[i['list_index']].get('physical_index')} for i in incorrect]))
        return result,incorrect

    def match_pages(part, structure, model=None):
        from . import index_recovery
        # The SDK asks the model to repeat the entire TOC for every chunk.
        # A partial answer or output truncation changes its entry count.
        # Ask only for ID/page pairs, then merge into the unchanged TOC.
        entries = [structure] if isinstance(structure, dict) else structure
        part_text = ''.join(part) if isinstance(part, list) else part
        pending = [{'id': i, 'title': item['title']}
                   for i, item in enumerate(entries)
                   if item.get('physical_index') is None]
        if not pending:
            return copy.deepcopy(entries)
        prompt = classic._SYSTEM_HARDENING + '''
Match directory titles to section start headings in the supplied document pages.
Use only physical_index markers in these pages. A mention in a table of contents
or in running prose is not a section start. Return only matches you can locate.
Keep each numeric id exactly. Do not repeat titles, invent entries, or infer page
offsets. Return JSON {"matches":[{"id":0,"physical_index":12}]}.
Return {"matches":[]} if no target section starts in these pages.
Targets:\n''' + classic._secure_doc_text(json.dumps(pending, ensure_ascii=False))
        prompt += '\nDocument pages:\n' + classic._secure_doc_text(part_text)
        context_note='\nOrdered directory context (source positions are candidates):\n'+classic._secure_doc_text(json.dumps([{'id':i,'title':e['title'],'physical_index':e.get('physical_index')} for i,e in enumerate(entries)],ensure_ascii=False))
        def validate(value):
            response,finish=value
            if finish!='finished':raise ValueError('Page matching output was truncated')
            parsed=classic.extract_json(response)
            if not isinstance(parsed,dict):raise ValueError('Page matching must return a JSON object')
            matches=parsed.get('matches');valid=classic._extract_chunk_marker_set(part_text)
            if not isinstance(matches,list):raise ValueError('Page matching must return a list')
            unresolved=[]
            for match in matches:
                if not isinstance(match,dict) or type(match.get('id')) is not int or not 0<=match['id']<len(entries):raise ValueError('Page matching returned an unknown entry ID')
                # A repeated known ID is redundant output, not a new section.
                # Keep its existing position; never overwrite it from a later
                # chunk. The SDK still verifies every saved section start.
                if entries[match['id']].get('physical_index') is not None:continue
                page=match.get('physical_index')
                if isinstance(page,str):
                    marker=re.fullmatch(r'<physical_index_(\d+)>',page.strip());page=int(marker[1]) if marker else None
                if type(page) is not int or page not in valid:raise ValueError('Page matching returned an unsupported physical page')
                unresolved.append(match)
            result=reconcile_matches(classic,entries,unresolved,part_text,model)
            positions=[]
            for e in result:
                p=e.get('physical_index')
                if isinstance(p,str):
                    marker=re.fullmatch(r'<physical_index_(\d+)>',p.strip());p=int(marker[1]) if marker else None
                if type(p) is int:positions.append(p)
            if positions!=sorted(positions):raise ValueError('Page matching violates the original directory order')
            return result
        return index_recovery.run(lambda note:classic.llm_completion(model=model,prompt=prompt+(context_note if note else '')+note,return_finish_reason=True),validate,'directory page matching')

    def fill_missing(toc_items, page_list, start_index=1, model=None):
        if all(item.get('physical_index') is not None for item in toc_items):
            return toc_items
        # The SDK's previous/next-item range can be empty for a final missing
        # entry. Match unresolved entries against bounded physical-page chunks.
        contents = [f'<physical_index_{i}>\n{text}\n<physical_index_{i}>\n'
                    for i, (text, _) in enumerate(page_list, start_index)]
        lengths = [classic.count_tokens(text, model) for text in contents]
        result = copy.deepcopy(toc_items)
        for part in classic.page_list_to_group_text(contents, lengths):
            result = match_pages(part, result, model=model)
            if all(item.get('physical_index') is not None for item in result):
                break
        return classic.convert_physical_index_to_int(result)

    def checked_offset(data, offset):
        if offset is None:
            raise MissingPageOffset('No verified printed-to-physical page offset')
        return add_offset(data, offset)

    def with_fallback(toc_content, toc_page_list, page_list,
                      toc_check_page_num=None, model=None, logger=None):
        try:
            return process(toc_content, toc_page_list, page_list,
                           toc_check_page_num=toc_check_page_num,
                           model=model, logger=logger)
        except MissingPageOffset:
            if logger:
                logger.info({'compatibility': 'missing_offset_physical_page_matching'})
            return classic.process_toc_no_page_numbers(
                toc_content, toc_page_list, page_list, model=model, logger=logger)

    classic.add_page_offset_to_toc_json = checked_offset
    classic.add_page_number_to_toc = match_pages
    classic.process_none_page_numbers = fill_missing
    classic.process_toc_with_page_numbers = with_fallback
    classic.check_title_appearance = title_start
    classic.verify_toc = verify
    classic.check_title_appearance_in_start_concurrent = boundaries
    classic.fix_incorrect_toc_with_retries = checked_repair
    classic.meta_processor = metadata
    classic.process_large_node_recursively = subdivide
    classic._carefold_offset_fix = True
