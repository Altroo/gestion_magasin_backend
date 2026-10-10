from datetime import timedelta
import threading
import uuid
from django.conf import settings
from django.db import close_old_connections
from django.db.models import Q
from django.utils import timezone
from chat_ai_assistant.contracts import ChatAIError
from chat_ai_assistant.provider import ModelConfig
from .provider import ChatAIMagasinModelService
from chat_ai_assistant.orchestrator import ChatAIOrchestrator
from .models import Conversation, Message, InferenceLease, KnowledgeDocument
from .planner import SYSTEM,shortlist
from .security import authorization_stamp, validate_text
from .tools import ChatAIToolExecutor, registry
from .resources import RESOURCES
from .labels import FIELD_LABELS, FIELD_LABELS_EN, selected_action_text
from chat_ai_assistant.clarifications import message_language
from chat_ai_assistant.presentation import labelled_text
from .shortcuts import shortcut_action, reference_action, knowledge_action, greeting_action


def get_conversation(user_id, id):
    conv=Conversation.objects.filter(pk=id,user_id=user_id,expires_at__gt=timezone.now()).first()
    if conv is None:raise ChatAIError('NOT_FOUND')
    if conv.authorization_stamp!=authorization_stamp(user_id,conv.company_id):
        raise ChatAIError('CONTEXT_EXPIRED')
    return conv


def authorize_delivery(user_id, conversation_id, knowledge_sources=None, cards=()):
    conv = get_conversation(user_id, conversation_id)
    source_groups = [knowledge_sources] if knowledge_sources is not None else []
    # Replayed knowledge cards may come from a fresh retrieval, so guard their
    # sources as well as the original sources supporting persisted prose.
    for card in cards:
        if card.get('type') == 'knowledge' and card.get('documents'):
            source_groups.append([{'document_id': doc['document_id'], 'version': doc['version']}
                                  for doc in card['documents']])
    # Revalidate references immediately before delivery, including staff revocation
    # or a record moved into another company while inference was running.
    executor = ChatAIToolExecutor(user_id, conv.company_id, uuid.uuid4(), audit=False)
    for card in cards:
        if card.get('type') == 'record_list' and card.get('items'):
            resource=card['resource']
            ids=[item['id'] for item in card['items']]
            executor.context['interface_language']=card.get('language','fr')
            fresh_items=executor.read_records(resource,ids)
            if len(fresh_items) != len(ids):
                raise ChatAIError('CONTEXT_EXPIRED')
            # Deliver the freshly authorized projection, never the stale related names.
            card['items']=fresh_items
        if card.get('type') == 'confirmation':
            from .actions import replay_confirmation
            if replay_confirmation(executor, {'confirmation_id': card['action_id']})['type'] != 'confirmation':
                raise ChatAIError('CONTEXT_EXPIRED')
        if card.get('type')=='financial_summary' and 'financial' not in executor.capabilities():
            raise ChatAIError('CONTEXT_EXPIRED')
        if card.get('type')=='pdf':
            executor.sale_document(card['record_id'],card['language'])
        if card.get('type')=='navigation':
            target=card['target']
            executor.navigate(target['resource'],identifier=target.get('identifier'))
    if source_groups:
        from .knowledge import ChatAIKnowledgeService
        executor = ChatAIToolExecutor(user_id, conv.company_id, uuid.uuid4(), audit=False)
        caps = executor.capabilities()
        if any(not ChatAIKnowledgeService.sources_authorized(sources, conv.company_id, caps)
               for sources in source_groups):
            raise ChatAIError('CONTEXT_EXPIRED')
    return conv


def get_model(interface_language='fr'):
    return ChatAIMagasinModelService(ModelConfig(settings.CHAT_AI_MODEL_URL,settings.CHAT_AI_MODEL_ID,
        settings.CHAT_AI_MODEL_KEY,settings.CHAT_AI_MODEL_TIMEOUT,settings.CHAT_AI_MODEL_MAX_TOKENS,mode='native'),interface_language=interface_language)


def replay(executor, action):
    if not action:return []
    if action.get('confirmation_id'):
        from .actions import replay_confirmation
        return [replay_confirmation(executor, action)]
    from .resources import RESOURCES
    resource=action.get('resource')
    executor.context['interface_language']=action.get('language','fr')
    if resource in RESOURCES:
        return [{'type':'record_list','language':action.get('language','fr'),'resource':resource,'items':executor.read_records(resource,action.get('ids',[])[:10])}]
    if action.get('tool') in ('navigate','knowledge','sale_document','financial_summary'):
        return [executor.execute(action['tool'],action['arguments'])]
    return []


def knowledge_sources_authorized(executor, action):
    """Saved prose is usable only while every exact original source remains approved."""
    from .knowledge import ChatAIKnowledgeService
    return ChatAIKnowledgeService.sources_authorized(
        action.get('knowledge_sources'), executor.company_id, executor.capabilities())


def replay_message(executor, message):
    """Refresh cards and withhold generated knowledge prose with revoked/stale sources."""
    text = message.text
    if message.role=='assistant':
        language=message.action.get('language') or message_language(text,executor.context.get('interface_language','fr'))
        try:text=labelled_text(text,FIELD_LABELS_EN if language=='en' else FIELD_LABELS)
        except ChatAIError:text=''
    elif message.action.get('selected_resource'):
        legacy_verb=message.text.split(' · ',1)[0]
        operation=message.action.get('selected_operation') or {'Modifier':'edit','Supprimer':'delete','Edit':'edit','Delete':'delete'}.get(legacy_verb)
        language=message.action.get('language') or ('en' if legacy_verb in ('Edit','Delete') else 'fr')
        if operation in ('edit','delete'):
            text=selected_action_text(operation,message.action['selected_resource'],language)
    knowledge_answer = message.role == 'assistant' and message.action.get('tool') == 'knowledge'
    try:
        cards = replay(executor, message.action)
        if knowledge_answer and not knowledge_sources_authorized(executor, message.action):
            text = ''
    except ChatAIError:
        cards = []
        if knowledge_answer:
            text = ''
    return {'id': str(message.pk), 'role': message.role, 'text': text, 'cards': cards}


def stored_action(result, language='fr'):
    return {**_stored_action(result, language), 'language': 'en' if language == 'en' else 'fr'}


def _stored_action(result, language='fr'):
    cards=result.get('cards',[])
    if cards and cards[0].get('type') == 'confirmation':
        return {'confirmation_id': cards[0]['action_id'], 'language': 'en' if language == 'en' else 'fr'}
    if cards and cards[0].get('type')=='pdf':
        return {'tool':'sale_document','arguments':{'identifier':cards[0]['record_id'],'language':cards[0]['language']}}
    if cards and cards[0].get('type')=='navigation':
        target=cards[0]['target'];args={'resource':target['resource']}
        if target.get('identifier'):args['identifier']=target['identifier']
        return {'tool':'navigate','arguments':args}
    if cards and cards[0].get('resource') in RESOURCES:
        card=cards[0]
        return {'resource':card['resource'],'ids':[x['id'] for x in card.get('items',[])]}
    action=result.get('action',{})
    if action.get('tool') == 'knowledge':
        sources = [{'document_id': doc['document_id'], 'version': doc['version']}
                   for card in cards if card.get('type') == 'knowledge'
                   for doc in card.get('documents', [])]
        return {**action, 'knowledge_sources': sources}
    return {} if action.get('tool')=='prepare_change' else action


class _DeferredKnowledgeModel:
    # Reviewed excerpts need no inference connection. Legacy approved documents
    # still load the normal private provider when they require generation.
    def stream(self, *args, **kwargs):
        return get_model().stream(*args, **kwargs)


class ChatAIConversationService:
    def run(self,user_id,conversation_id,text,request_id,context,emit,cancel):
        close_old_connections()
        owner=uuid.uuid4();acquired=False
        try:
            conv=get_conversation(user_id,conversation_id)
            text=validate_text(text)
            prior_user=conv.messages.filter(request_id=request_id,role='user').first()
            if prior_user is not None and prior_user.text!=text:raise ChatAIError('INVALID_ARGUMENTS')
            complete=conv.messages.filter(request_id=request_id,role='assistant').first()
            if complete:
                executor=ChatAIToolExecutor(user_id,conv.company_id,request_id,audit=False)
                response = replay_message(executor, complete)
                authorize_delivery(user_id, conversation_id, cards=response['cards'])
                if complete.action.get('tool') == 'knowledge':
                    emit('_knowledge.sources', {'sources': complete.action.get('knowledge_sources', [])})
                return response
            InferenceLease.objects.get_or_create(name='model')
            acquired=bool(InferenceLease.objects.filter(name='model').filter(Q(owner__isnull=True)|Q(expires_at__lt=timezone.now())).update(owner=owner,expires_at=timezone.now()+timedelta(seconds=settings.CHAT_AI_MODEL_TIMEOUT*2+60)))
            if not acquired:raise ChatAIError('BUSY')
            if conv.messages.count()>=60:raise ChatAIError('CONTEXT_LIMIT')
            user_message,created=Message.objects.get_or_create(conversation=conv,request_id=request_id,role='user',defaults={'text':text})
            if not created and user_message.text!=text:raise ChatAIError('INVALID_ARGUMENTS')
            context=dict(context)
            context["interface_language"]=message_language(text,context.get("interface_language","fr"))
            # Bind inline selection to its original page and retryable request.
            # A newly navigated page takes precedence; a failed turn keeps its target.
            page_hint={key:context[key] for key in ('resource','identifier') if key in context}
            selected=conv.references.get('selected')
            same_page=conv.references.get('selection_origin',{})==page_hint
            same_turn=conv.references.get('selection_request_id') in (None,str(request_id))
            if selected and same_page and same_turn and conv.references.get('expires_at','')>timezone.now().isoformat() and len(conv.references.get('ids',[]))==1:
                context.update(resource=conv.references['resource'],identifier=conv.references['ids'][0])
                conv.references['selection_request_id']=str(request_id)
                conv.save(update_fields=['references','updated_at'])
            elif selected:
                for key in ('selected','selection_origin','selection_request_id'):conv.references.pop(key,None)
                conv.save(update_fields=['references','updated_at'])
            executor=ChatAIToolExecutor(user_id,conv.company_id,request_id,conv.references,context,instruction=text)
            # Only user utterances, not historic business output, enter planner context.
            history=list(conv.messages.filter(role='user').exclude(pk=user_message.pk).order_by('-created_at')[:4])
            trusted={'application':'gestion_magasin','today':timezone.localdate().isoformat(),
                     'selected_company':conv.company_id,
                     'capabilities':sorted(executor.capabilities()),
                     'interface_language':context.get('interface_language','fr'),
                     'current_resource':context.get('resource'),
                     'current_identifier':context.get('identifier'),
                     'previous_result_type':conv.references.get('resource'),
                     'previous_result_count':len(conv.references.get('ids',[]))}
            greeting=greeting_action(text)
            if not greeting and (context.get('resource') or context.get('identifier')):
                try:executor.record(context.get('resource'),context.get('identifier'))
                except ChatAIError as exc:
                    if exc.code not in ('NOT_FOUND','PERMISSION_DENIED'):raise
                    context.pop('resource',None);context.pop('identifier',None)
                    trusted.update(current_resource=None,current_identifier=None)
            forced=greeting or shortcut_action(text,executor,trusted['interface_language']) or reference_action(text,conv.references) or knowledge_action(text)
            model = _DeferredKnowledgeModel() if forced and forced['tool'] == 'knowledge' else (None if forced else get_model(trusted['interface_language']))
            result=ChatAIOrchestrator(model,registry(),executor,system_prompt=SYSTEM,tool_selector=shortlist).run(text,context=trusted,forced_action=forced,
                history=[{'role':'user','content':m.text} for m in reversed(history)],emit=emit,cancel=cancel)
            if cancel.is_set():raise ChatAIError('CANCELLED')
            # Recheck immediately before persistence/delivery for JSON and SSE alike.
            authorize_delivery(user_id,conversation_id,cards=result['cards'])
            for card in result['cards']:
                if card.get('type') == 'knowledge' and card.get('documents'):
                    executor.authorize_knowledge(card['documents'])
            assistant=Message.objects.create(conversation=conv,request_id=request_id,role='assistant',text=result['text'][:6000],action=stored_action(result, context.get('interface_language', 'fr')))
            for key in ('selected','selection_origin','selection_request_id'):executor.state.pop(key,None)
            conv.references=executor.state;conv.save(update_fields=['references','updated_at'])
            return {'id':str(assistant.pk),'role':'assistant','text':assistant.text,'cards':result['cards']}
        finally:
            if acquired:InferenceLease.objects.filter(name='model',owner=owner).update(owner=None,expires_at=None)
            close_old_connections()
