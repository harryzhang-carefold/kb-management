# Source provenance and isolation

This service is owned and operated by Carefold. Its only indexing dependency is
VectifyAI/PageIndex commit `6d23caf416858f2ca136840305d1f479a86f6ef7`.
The SDK's MIT license is preserved in PAGEINDEX-LICENSE.

The following logic was copied, with the owner's explicit permission, from
Feynman commit `f3491ec` and adapted into this repository:

- `pageindex_compat.py`, `index_lane.py`, `index_recovery.py`,
  `index_boundaries.py`, `index_source_repair.py`: bounded recovery, exact
  physical-page matching, ordered OCR evidence, verified-section retention.
- `ocr.py`: source-preserving OCR text layers and language-data cache revisions.
- `documents.py`: NFC/spacing-only quote comparison, stable passage catalog,
  unique exact quote positions and glyph-coordinate recovery.
- `models.py`: separate claim support and original-crop OCR checks.

The source project has no root LICENSE; these copies are authorized by its owner.
No source checkout, Python environment, database, HTTP endpoint, model settings,
UI module or OCR asset is imported or linked at runtime. The source project is
not changed. Standard indexing patches apply only inside this service process.

OCR uses the deployment's Tesseract language packages, installed by the service
Dockerfile, rather than assets copied from the source project. Distribution
licenses are retained by Debian's package manager under /usr/share/doc.

requirements.lock.txt was resolved and frozen in Carefold's own Python 3.12
virtual environment. Both macOS development and Linux server images use the same
pinned SDK revision; no editable or local-path dependency is allowed.

The 2026-10 KB migration adapts the complete Carefold Knowledge implementation
from carefold-agent bf4fdee into app.knowledge. MinIO remains the original-file
authority; PostgreSQL stores versions and Invocation delivery receipts. Temporary
PDF/OCR/SDK workspaces are removed when processing ends. KB ownership and
membership replace the standalone service policy file. No Carefold Agent or
Feynman runtime dependency is introduced. OCR language packages are installed
on the KB host; requirements.lock.txt pins the tested shared API/worker/MCP runtime.
