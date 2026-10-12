"""Resolve trusted Runtime principals to existing KB account permissions."""
import json
import secrets
from contextvars import ContextVar
from uuid import UUID

from sqlalchemy import or_, select
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import decode_token
from app.models import User, KnowledgeBase, KbMember, Document
from .service import KnowledgeService

request_headers = ContextVar('knowledge_request_headers', default={})


def accessible_kb_ids():
    """Apply the same account permissions to the existing six KB tools."""
    headers = request_headers.get()
    token = headers.get('authorization', '').removeprefix('Bearer ')
    if settings.kb_mcp_api_key and secrets.compare_digest(token.encode(), settings.kb_mcp_api_key.encode()):
        scope, _ = KBKnowledgeService().scope(headers.get('x-carefold-interaction-scope'),
            headers.get('x-carefold-scope-issued-at'), headers.get('x-carefold-scope-signature'))
        user_id, role = authenticated_user(headers, scope)
    else:
        subject = decode_token(token, 'access')
        try:
            ident = UUID(subject) if subject else None
        except ValueError:
            ident = None
        with SessionLocal() as db:
            user = db.query(User).filter_by(id=ident, is_active=True).first() if ident else None
            if user is None:
                raise PermissionError('Knowledge account unavailable or not authorized')
            user_id, role = user.id, user.role
    with SessionLocal() as db:
        query = db.query(KnowledgeBase.id).filter(KnowledgeBase.is_deleted.is_(False))
        if role != 'admin':
            memberships = select(KbMember.kb_id).where(KbMember.user_id == user_id)
            query = query.filter(or_(KnowledgeBase.owner_id == user_id, KnowledgeBase.id.in_(memberships)))
        return [ident for (ident,) in query.all()]


def authenticated_user(headers, scope):
    authorization = headers.get('authorization', '')
    token = authorization[7:] if authorization.startswith('Bearer ') else ''
    service_credential = bool(settings.kb_mcp_api_key) and secrets.compare_digest(
        token.encode(), settings.kb_mcp_api_key.encode())
    with SessionLocal() as db:
        if service_credential:
            binding = settings.kb_mcp_actor_bindings.get(scope.get('actorId'))
            if not binding or scope.get('organizationId') != settings.kb_mcp_organization_id:
                raise PermissionError('Knowledge Actor binding required')
            user = db.query(User).filter_by(username=binding, is_active=True).first()
        else:
            subject = decode_token(token, 'access')
            try:
                subject = UUID(subject) if subject else None
            except ValueError:
                subject = None
            user = db.query(User).filter_by(id=subject, is_active=True).first() if subject else None
            # A user token cannot be used to impersonate a different Runtime Actor.
            binding = settings.kb_mcp_actor_bindings.get(scope.get('actorId'))
            if user and binding != user.username:
                user = None
        if user is None:
            raise PermissionError('Knowledge account unavailable or not authorized')
        return user.id, user.role


class KBKnowledgeService(KnowledgeService):
    def __init__(self):
        self.token = settings.kb_mcp_api_key
        if len(self.token.encode()) < 32:
            raise ValueError('Knowledge MCP requires an independent service credential')
        self.signing_secret = settings.carefold_scope_signing_secret
        self.organization_id = settings.kb_mcp_organization_id

    def policy(self):
        headers = request_headers.get()
        # Scope decoding and signature checks remain in the inherited scope method.
        import base64
        try:
            raw = headers.get('x-carefold-interaction-scope', '')
            if not raw or len(raw) > 16000:
                raise ValueError()
            scope = json.loads(base64.urlsafe_b64decode(raw + '=' * (-len(raw) % 4)))
            if not isinstance(scope, dict):
                raise ValueError()
        except (ValueError, TypeError, UnicodeError):
            raise PermissionError('Complete trusted Interaction Scope required') from None
        user_id, role = authenticated_user(headers, scope)
        with SessionLocal() as db:
            query = db.query(Document).join(KnowledgeBase, Document.kb_id == KnowledgeBase.id).filter(
                Document.is_deleted.is_(False), KnowledgeBase.is_deleted.is_(False),
                Document.status == 'indexed')
            if role != 'admin':
                memberships = select(KbMember.kb_id).where(KbMember.user_id == user_id)
                query = query.filter(or_(KnowledgeBase.owner_id == user_id, KnowledgeBase.id.in_(memberships)))
            # Read only control metadata after checking the actual account permissions.
            documents = query.with_entities(Document.id, Document.kb_id, Document.meta).all()
            identifiers, sources = [], []
            for ident, kb_id, metadata in documents:
                evidence = (metadata or {}).get('pageindex_evidence')
                if evidence:
                    identifiers.append(evidence['document_id'])
                    sources.append(f'kb:{kb_id}:document:{ident}')
        return {'organization_id': self.organization_id,
                'agent_definition_ids': settings.kb_mcp_agent_definition_ids,
                'source_ids': sources, 'document_ids': identifiers}

    def call(self, *args, **kwargs):
        from . import store
        with store.workspace():
            return super().call(*args, **kwargs)

    def document(self, ident, version, scope, policy):
        if ident not in policy['document_ids']:
            raise PermissionError('Knowledge Source unavailable or not authorized')
        return super().document(ident, version, scope, policy)

    @staticmethod
    def metadata(doc):
        from app.core.security import create_view_token
        metadata = KnowledgeService.metadata(doc)
        source = doc['source_metadata']
        if source.get('kb_document_id') and source.get('kb_id'):
            import base64
            encoded = request_headers.get().get('x-carefold-interaction-scope', '')
            scope = json.loads(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)))
            token = create_view_token(source['kb_document_id'], source['kb_id'], scope['actorId'])
            base = settings.kb_public_base_url.rstrip('/')
            metadata['doc_url'] = f"{base}/kb/{source['kb_id']}/doc/{source['kb_document_id']}?token={token}"
            metadata['kb_id'] = source['kb_id']
            metadata['kb_document_id'] = source['kb_document_id']
        return metadata
