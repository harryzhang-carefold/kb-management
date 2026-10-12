"""RAG 问答路由 /knowledge-bases/{kb_id}/chat — SSE 流式"""
import json
import uuid
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from uuid import UUID

from app.core.responses import ok, not_found
from app.core.database import get_db
from app.schemas import schemas
from app.models import *
from app.api.deps import get_current_user, require_kb_access
from app.services.rag_engine import rag_engine

router = APIRouter(tags=["RAG 问答"])


@router.post("/knowledge-bases/{kb_id}/chat")
async def chat(kb_id: UUID, req: schemas.ChatReq,
               db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    kb = db.query(KnowledgeBase).filter_by(id=kb_id, is_deleted=False).first()
    if not kb:
        raise not_found("知识库不存在")
    require_kb_access(user, kb)

    # 确定/创建会话
    if req.conversation_id:
        conv = db.query(Conversation).filter(
            Conversation.id == req.conversation_id,
            Conversation.kb_id == kb_id,
            Conversation.user_id == user.id,
        ).first()
        if not conv:
            raise not_found("会话不存在")
    else:
        conv = Conversation(kb_id=kb_id, user_id=user.id,
                                   title=req.question[:50])
        db.add(conv)
        db.commit()
        db.refresh(conv)

    # 存用户消息
    user_msg = Message(
        conversation_id=conv.id, role="user",
        content=req.question,
        token_count=len(req.question) // 2,
    )
    db.add(user_msg)
    db.commit()

    # 取历史
    history = []
    if req.history:
        history = [{"role": h.role, "content": h.content} for h in req.history]
    else:
        msgs = db.query(Message).filter(
            Message.conversation_id == conv.id
        ).order_by(Message.created_at.desc()).limit(6).all()
        history = [{"role": m.role, "content": m.content} for m in reversed(msgs)]
        # 去掉当前问题（刚存的）
        if history and history[0]["role"] == "user" and history[0]["content"] == req.question:
            history = history[1:]

    def sse_gen():
        # meta
        full_answer = ""
        sources = []
        for event in rag_engine.stream_answer(
            kb_id=str(kb_id), question=req.question,
            history=history, top_n=req.top_n,
            system_prompt=req.system_prompt,
            retrieval_mode=req.retrieval_mode,
            db=db,
        ):
            etype = event.get("type")
            if etype == "meta":
                sources = event.get("sources", [])
                meta_payload = {"conversation_id": str(conv.id)}
                # F6：auto 的 0 命中/降级提示走 meta.notice（非 error 事件）
                if event.get("notice"):
                    meta_payload["notice"] = event["notice"]
                yield f"event: meta\ndata: {json.dumps(meta_payload, ensure_ascii=False)}\n\n"
            elif etype == "token":
                full_answer += event["token"]
                yield f"event: token\ndata: {json.dumps({'token': event['token']}, ensure_ascii=False)}\n\n"
            elif etype == "done":
                full_answer = event.get("full", full_answer)
                # 存 assistant 消息
                assistant_msg = Message(
                    conversation_id=conv.id, role="assistant",
                    content=full_answer, sources=sources,
                    token_count=event.get("token_count", 0),
                )
                db.add(assistant_msg)
                conv.message_count += 2
                db.commit()
                yield f"event: sources\ndata: {json.dumps({'sources': sources}, ensure_ascii=False)}\n\n"
                yield f"event: done\ndata: {json.dumps({'token_count': event.get('token_count', 0), 'finish_reason': 'stop'}, ensure_ascii=False)}\n\n"
            elif etype == "error":
                yield f"event: error\ndata: {json.dumps({'message': event.get('message')}, ensure_ascii=False)}\n\n"
        db.close()

    return StreamingResponse(
        sse_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/knowledge-bases/{kb_id}/conversations")
def list_conversations(kb_id: UUID,
                       page: int = 1, page_size: int = 20,
                       db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    kb = db.query(KnowledgeBase).filter_by(id=kb_id, is_deleted=False).first()
    if not kb:
        raise not_found("知识库不存在")
    require_kb_access(user, kb)
    q = db.query(Conversation).filter(
        Conversation.kb_id == kb_id,
        Conversation.user_id == user.id,
    )
    total = q.count()
    items = q.order_by(Conversation.updated_at.desc()) \
        .offset((page - 1) * page_size).limit(page_size).all()
    return ok({
        "items": [schemas.ConversationOut.model_validate(c) for c in items],
        "total": total, "page": page, "page_size": page_size,
    })


@router.get("/knowledge-bases/{kb_id}/conversations/{conv_id}")
def get_conversation(kb_id: UUID, conv_id: UUID,
                     db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    kb = db.query(KnowledgeBase).filter_by(id=kb_id, is_deleted=False).first()
    if not kb:
        raise not_found("知识库不存在")
    require_kb_access(user, kb)
    conv = db.query(Conversation).filter(
        Conversation.id == conv_id,
        Conversation.kb_id == kb_id,
        Conversation.user_id == user.id,
    ).first()
    if not conv:
        raise not_found("会话不存在")
    msgs = db.query(Message).filter(
        Message.conversation_id == conv.id
    ).order_by(Message.created_at).all()
    return ok(schemas.ConversationDetailOut(
        conversation=schemas.ConversationOut.model_validate(conv),
        messages=[schemas.MessageOut.model_validate(m) for m in msgs],
    ))


@router.delete("/knowledge-bases/{kb_id}/conversations/{conv_id}")
def delete_conversation(kb_id: UUID, conv_id: UUID,
                        db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    kb = db.query(KnowledgeBase).filter_by(id=kb_id, is_deleted=False).first()
    if not kb:
        raise not_found("知识库不存在")
    require_kb_access(user, kb)
    conv = db.query(Conversation).filter(
        Conversation.id == conv_id,
        Conversation.user_id == user.id,
    ).first()
    if not conv:
        raise not_found("会话不存在")
    db.delete(conv)
    db.commit()
    return ok({})
