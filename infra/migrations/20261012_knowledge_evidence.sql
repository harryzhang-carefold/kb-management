BEGIN;
CREATE TABLE IF NOT EXISTS pageindex_record (
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(kind,key)
);
CREATE TABLE IF NOT EXISTS pageindex_evidence_receipt (
    scope TEXT NOT NULL,
    document TEXT NOT NULL,
    version TEXT NOT NULL,
    page INTEGER NOT NULL,
    passage TEXT NOT NULL,
    start INTEGER NOT NULL,
    "end" INTEGER NOT NULL,
    total INTEGER NOT NULL,
    expires DOUBLE PRECISION NOT NULL,
    PRIMARY KEY(scope,document,version,page,passage,start)
);
CREATE INDEX IF NOT EXISTS pageindex_receipt_expiry ON pageindex_evidence_receipt(expires);
COMMIT;
