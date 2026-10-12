#!/usr/bin/env python3
"""Apply additive Knowledge schema to an existing KB database."""
import sys
from pathlib import Path
from sqlalchemy import text
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'backend'))
from app.core.database import engine
engine.echo = False
with engine.begin() as connection:
    for statement in (root / 'infra/migrations/20261012_knowledge_evidence.sql').read_text().split(';'):
        if statement.strip() and statement.strip() not in {'BEGIN', 'COMMIT'}:
            connection.execute(text(statement))
print('Additive Knowledge schema applied; existing KB data preserved.')
