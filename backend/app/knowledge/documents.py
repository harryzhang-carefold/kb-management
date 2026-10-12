"""Versioned PageIndex trees and exact source passages, adapted as independent code."""
import hashlib
import json
import re
import shutil
import tempfile
import threading
import unicodedata
from pathlib import Path

import pymupdf
from . import ocr, store

SDK_REVISION = '6d23caf416858f2ca136840305d1f479a86f6ef7'
POLICY = 'carefold-pageindex-1'
INDEX_LOCK = threading.Lock()


def digest(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def norm(text):
    # Preserve case and mathematical symbol identity; ignore spacing only.
    return re.sub(r'\s+', '', unicodedata.normalize('NFC', text))


def passage_catalog(page, text):
    chunks, pending = [], ''
    for piece in re.split(r'(?<=[.!?。！？])\s+', text):
        pending = (pending + ' ' + piece).strip()
        if len(norm(pending)) >= 8 and norm(text).count(norm(pending)) == 1:
            chunks.append(pending)
            pending = ''
    if pending:
        if chunks: chunks[-1] += ' ' + pending
        else: chunks.append(pending)
    return [{'id': f'p{page}-{i:03d}', 'text': quote} for i, quote in enumerate(chunks, 1)]


def quote_boxes(path, number, quote):
    if len(norm(quote)) < 8: return []
    with pymupdf.open(path) as pdf:
        page = pdf[number - 1]
        if norm(page.get_text()).count(norm(quote)) != 1: return []
        rects = page.search_for(quote)
        if not rects:
            chars, text = [], []
            for block in page.get_text('rawdict')['blocks']:
                for line in block.get('lines', []):
                    for span in line['spans']:
                        for char in span['chars']:
                            for c in norm(char['c']):
                                text.append(c); chars.append((id(line), char['bbox']))
            text = ''.join(text); needle = norm(quote)
            if text.count(needle) != 1: return []
            start = text.index(needle); lines = {}
            for line, bbox in chars[start:start + len(needle)]:
                if line not in lines: lines[line] = pymupdf.Rect(bbox)
                else: lines[line] |= pymupdf.Rect(bbox)
            rects = list(lines.values())
        w, h = page.rect.width, page.rect.height
        return [[r.x0/w, r.y0/h, r.x1/w, r.y1/h] for rect in rects for r in [rect * page.rotation_matrix]]


def validate_tree(tree, page_count, parent=None, seen=None):
    seen = set() if seen is None else seen
    if not isinstance(tree, list) or not tree: raise ValueError('PageIndex tree is empty')
    previous = 0
    for node in tree:
        a, b = node.get('start_index'), node.get('end_index')
        ident = node.get('node_id')
        if type(a) is not int or type(b) is not int or not 1 <= a <= b <= page_count:
            raise ValueError('Invalid physical-page range')
        if a < previous or (parent and not parent[0] <= a <= b <= parent[1]):
            raise ValueError('PageIndex tree violates directory order or parent range')
        if not isinstance(ident, str) or not ident or ident in seen: raise ValueError('Invalid or duplicate node ID')
        if not isinstance(node.get('title'), str) or not node['title']: raise ValueError('Missing section title')
        seen.add(ident); previous = a
        if node.get('nodes'): validate_tree(node['nodes'], page_count, (a, b), seen)


def prepare_pdf(original, work):
    processed = work / 'processed.pdf'
    pages, labels, scanned = [], [], []
    revision = None
    with pymupdf.open(original) as pdf:
        if pdf.needs_pass or not len(pdf): raise ValueError('PDF must have pages and no password')
        for i, page in enumerate(pdf, 1):
            text = page.get_text()
            labels.append(page.get_label() or None)
            if ocr.needed(page, text):
                if revision is None: revision = ocr.cache_revision()
                layer, _ = ocr.text_layer(page, work / 'ocr' / f'{revision}-{i}.pdf')
                try: ocr.add_layer(page, layer)
                finally: layer.close()
                text = page.get_text(); scanned.append(i)
            pages.append({'page_index': i, 'markdown': text})
        if scanned: pdf.save(processed, garbage=4, deflate=True)
    return (processed if scanned else original), pages, labels, scanned


def build_tree(path, pages, scanned):
    from pageindex.flash import page_index_flash
    from pageindex.flash.api import flash_rejection_reason
    from pageindex.utils import write_node_id
    reason = None
    with pymupdf.open(path) as pdf:
        if scanned and not pdf.get_toc(): reason = 'OCR needs source-checked Standard indexing'
    if not reason:
        result = page_index_flash(str(path), summary=False, optimize=False)
        reason = flash_rejection_reason(result)
    if not reason:
        tree = result['structure']; write_node_id(tree)
        return tree, result.get('toc_source', 'flash')
    from pageindex import PageIndexClient
    from . import index_lane
    from .models import backend
    from .pageindex_compat import PreparedText, StructureConfig
    model, config = backend()
    index_lane.install()
    pi = PageIndexClient(index={'model': 'openai/' + model, 'backend': config,
                               'storage_path': str(store.data_dir() / 'sdk'), 'optimize': 'off'})
    pi._api._config_loader = StructureConfig(pi._api._config_loader)
    # Distinct SDK filenames avoid its 99-name collision limit across sources.
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix='.pdf', prefix='index-') as source:
        shutil.copyfile(path, source.name)
        pi._api._extract_page_texts = PreparedText(source.name, pages, len(pages))
        indexed = pi.submit_document(source.name, mode='standard')
    return pi._api.raw_tree(indexed['doc_id']), 'standard-model'


def import_pdf(path, *, title, organization_id, source_id, source_metadata=None, force=False):
    if not all(isinstance(x, str) and x.strip() for x in [title, organization_id, source_id]):
        raise ValueError('Title, Organization and Knowledge Source are required')
    ident = hashlib.sha256(json.dumps([organization_id, source_id]).encode()).hexdigest()
    with INDEX_LOCK:
        sha = digest(path)
        old = store.get('document', ident)
        ocr_revision = ocr.cache_revision() if old and old.get('ocr_pages') else None
        if old and old['sha256'] == sha and old['policy'] == POLICY and old.get('ocr_revision') == ocr_revision and not force:
            checked_document(ident)
            return old
        folder = store.data_dir() / 'documents' / ident
        folder.mkdir(parents=True, exist_ok=True)
        # Publish metadata only after every page and boundary passes validation.
        with tempfile.TemporaryDirectory(dir=folder) as temp:
            work = Path(temp); original = work / 'original.pdf'
            shutil.copyfile(path, original)
            if digest(original) != sha: raise ValueError('Source changed during import')
            reading, pages, labels, scanned = prepare_pdf(original, work)
            tree, engine = build_tree(reading, pages, scanned)
            validate_tree(tree, len(pages))
            reading_sha = digest(reading)
            version = hashlib.sha256(json.dumps([POLICY, sha, reading_sha, tree, pages], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            destination = folder / version
            if not destination.exists(): shutil.copytree(work, destination)
        record = {'id': ident, 'version': version, 'sha256': sha, 'reading_sha256': reading_sha,
                  'organization_id': organization_id, 'source_id': source_id, 'title': title,
                  'source_metadata': source_metadata or {}, 'policy': POLICY, 'sdk_revision': SDK_REVISION,
                  'page_count': len(pages), 'labels': labels, 'ocr_pages': scanned, 'tree': tree,
                  'ocr_revision': ocr.cache_revision() if scanned else None,
                  'artifacts': store.persist_files(destination, ident, version, source_metadata or {}),
                  'pages': pages, 'engine': engine}
        store.put('document_version', ident + ':' + version, record)
        return store.put('document', ident, record)


def paths(doc):
    root = store.materialize(doc)
    return root / 'original.pdf', root / ('processed.pdf' if doc['ocr_pages'] else 'original.pdf')


def checked_document(ident, version=None):
    doc = store.get('document', ident)
    if not doc: raise ValueError('Document not found')
    if version and doc['version'] != version: raise ValueError('Document version changed; read current evidence again')
    original, reading = paths(doc)
    if digest(original) != doc['sha256'] or digest(reading) != doc['reading_sha256']:
        raise ValueError('Source revision mismatch; rebuild the document')
    return doc
