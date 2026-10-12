"""Offline OCR. Preserve the original page pixels and add hidden source text."""
import math
import os
import hashlib
from pathlib import Path
import pymupdf

DATA_DIR=Path('/usr/share/tesseract-ocr/5/tessdata')
DEFAULT_LANGUAGES='eng+chi_sim+chi_tra'
REVISION='ocr-1'


def config(languages=None):
    from app.core.config import settings
    directory=Path(os.getenv('PAGEINDEX_TESSDATA') or settings.pageindex_tessdata)
    languages=os.getenv('PAGEINDEX_OCR_LANGUAGES') or languages or settings.pageindex_ocr_languages
    missing=[language for language in languages.split('+') if not (directory/f'{language}.traineddata').is_file()]
    if missing:raise ValueError('本地 OCR 语言包缺失：'+', '.join(missing)+'。请安装所配置的 Tesseract 语言包。')
    return directory,languages


def needed(page,text):
    if not text.strip():return bool(page.get_images() or page.get_drawings())
    # A page number or a short header must not hide a full scanned page.
    image=any(pymupdf.Rect(item['bbox']).get_area()>=page.rect.get_area()*.5 for item in page.get_image_info())
    if not image:return False
    if len(''.join(text.split()))<80:return True
    # Long digital headers and watermarks are not a full page text layer.
    bounds=pymupdf.Rect()
    for word in page.get_text('words'):bounds|=pymupdf.Rect(word[:4])
    return bounds.height<page.rect.height*.18


def cache_revision(languages=None):
    directory,languages=config(languages)
    # A language or trained-data change must not reuse old source text.
    digest=hashlib.sha256(languages.encode())
    for language in languages.split('+'):
        with (directory/f'{language}.traineddata').open('rb') as file:
            digest.update(hashlib.file_digest(file,'sha256').digest())
    return REVISION+'-'+digest.hexdigest()[:12]


def text_layer(page,cache,languages=None):
    directory,languages=config(languages)
    if cache.exists():
        cached=None
        try:
            # Graft maps retain the source document even after close(). Opening
            # its bytes avoids retaining one file handle per merged page.
            cached=pymupdf.open(stream=cache.read_bytes(),filetype='pdf')
            # A completed blank page is valid too. Re-running it can repeatedly
            # initialize Tesseract during assembly of a large scanned book.
            if len(cached)==1:
                cached[0].get_text()
                return cached,True
            cached.close()
        except (RuntimeError,ValueError):
            if cached is not None:cached.close()
        # Keep the old file until regeneration succeeds and atomically replaces it.
    rotation=page.rotation;page.set_rotation(0)
    try:
        scale=min(200/72,math.sqrt(12_000_000/max(1,page.rect.get_area())))
        pix=page.get_pixmap(matrix=pymupdf.Matrix(scale,scale),colorspace=pymupdf.csRGB,alpha=False)
        result=pymupdf.open(stream=pix.pdfocr_tobytes(language=languages,tessdata=str(directory)),filetype='pdf')
        layer=result[0]
        # Avoid copying the page image: only invisible GlyphLessFont text is used.
        for image in layer.get_images():layer.delete_image(image[0])
        sx,sy=layer.rect.width/page.rect.width,layer.rect.height/page.rect.height
        native=page.get_text('words')
        removed=False
        for x0,y0,x1,y1,text,*_ in layer.get_text('words'):
            rect=pymupdf.Rect(x0,y0,x1,y1)
            for nx0,ny0,nx1,ny1,original,*_ in native:
                if text.casefold()!=original.casefold():continue
                bounds=pymupdf.Rect(nx0*sx,ny0*sy,nx1*sx,ny1*sy)
                if (rect&bounds).get_area()>rect.get_area()*.4:
                    layer.add_redact_annot(rect,fill=False,cross_out=False);removed=True;break
        if removed:layer.apply_redactions(images=0,graphics=0)
        cache.parent.mkdir(parents=True,exist_ok=True)
        tmp=cache.with_suffix('.tmp.pdf')
        result.save(tmp,garbage=4,deflate=True);tmp.replace(cache)
        return result,False
    finally:page.set_rotation(rotation)


def add_layer(page,layer):
    rotation=page.rotation;page.set_rotation(0)
    try:
        if layer[0].get_text().strip():page.show_pdf_page(page.rect,layer,0,keep_proportion=False,overlay=True)
    finally:page.set_rotation(rotation)


def cache_page(source,number,cache,languages=None):
    """Process worker entry point. Never pass PDF objects across processes."""
    with pymupdf.open(source) as pdf:
        layer,cached=text_layer(pdf[number-1],Path(cache),languages)
        layer.close()
    return cached
