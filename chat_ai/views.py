import asyncio
from datetime import timedelta
import json
import queue
import threading
import uuid
from asgiref.sync import sync_to_async
from django.conf import settings
from django.http import StreamingHttpResponse
from django.db.models import OuterRef, Subquery
from django.db import OperationalError
from django.db.models.functions import Substr
from django.utils import timezone
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import Throttled
from rest_framework.response import Response
from rest_framework.renderers import JSONRenderer
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView
from chat_ai_assistant.contracts import ChatAIError
from .labels import selected_action_text, FIELD_LABELS
from chat_ai_assistant.presentation import labelled_text
from .models import Conversation, Feedback, Message
from .services import ChatAIConversationService, get_conversation, replay_message, authorize_delivery, stored_action
from .security import authorize, authorization_stamp, validate_text
from .tools import ChatAIToolExecutor
from .resources import RESOURCES


class StrictSerializer(serializers.Serializer):
    def to_internal_value(self,data):
        if not isinstance(data,dict) or set(data)-set(self.fields):
            raise serializers.ValidationError({'error':'Unsupported fields.'})
        return super().to_internal_value(data)


class NewConversation(StrictSerializer):
    company_id=serializers.IntegerField(min_value=1)


class Context(StrictSerializer):
    interface_language=serializers.ChoiceField(choices=['fr','en'],required=False)
    resource=serializers.ChoiceField(choices=list(RESOURCES),required=False)
    identifier=serializers.IntegerField(min_value=1,required=False)


class NewMessage(StrictSerializer):
    text=serializers.CharField(max_length=4000,trim_whitespace=True)
    request_id=serializers.UUIDField()
    context=Context(default=dict)


class FeedbackInput(StrictSerializer):
    message_id=serializers.UUIDField()
    helpful=serializers.BooleanField()


class ChatReadThrottle(UserRateThrottle):
    scope = 'chat_ai_read'
    rate = '120/minute'


class ChatMutationThrottle(UserRateThrottle):
    scope = 'chat_ai_mutation'
    rate = '60/minute'


class ChatInferenceThrottle(UserRateThrottle):
    scope = 'chat_ai_inference'
    rate = '12/minute'


class ChatConfirmationThrottle(UserRateThrottle):
    scope = 'chat_ai_confirmation'
    rate = '20/minute'


class ChatView(APIView):
    permission_classes=(IsAuthenticated,)
    throttle_classes=(ChatMutationThrottle,)

    def get_throttles(self):
        if self.request.method in ('GET', 'HEAD', 'OPTIONS'):
            return [ChatReadThrottle()]
        return super().get_throttles()

    def initial(self,request,*args,**kwargs):
        super().initial(request,*args,**kwargs)
        if not settings.CHAT_AI_ASSISTANT_ENABLED:raise ChatAIError('APPLICATION_UNAVAILABLE')

    def handle_exception(self,exc):
        if isinstance(exc,ChatAIError):
            code=exc.code
            status= {'NOT_FOUND':404,'NOT_AUTHENTICATED':401,'PERMISSION_DENIED':403,'APPLICATION_UNAVAILABLE':503,'BUSY':429,'CONTEXT_EXPIRED':409}.get(code,400)
            response=Response({'error':{'code':code}},status=status)
            response['Cache-Control']='no-store'
            return response
        response = super().handle_exception(exc)
        if isinstance(exc, Throttled) and exc.wait is not None:
            # The application's envelope rebuilds DRF responses without headers.
            response['Retry-After'] = str(exc.wait)
        return response

    def finalize_response(self,request,response,*args,**kwargs):
        response=super().finalize_response(request,response,*args,**kwargs)
        response['Cache-Control']='no-store, private'
        return response


class CapabilitiesView(ChatView):
    def get(self,request):
        from .security import authorize_identity, available_stores, capabilities
        from .shortcuts import shortcut_catalog, suggestions
        user=authorize_identity(request.user.pk)
        language=request.query_params.get('language','fr')
        companies=[]
        for store in available_stores(user):
            caps=capabilities(user,store.pk)
            companies.append({'id':store.pk,'name':store.name,'is_global_stock':store.is_global_stock,'code':store.code,'can_update':'update' in caps,'can_delete':'delete' in caps,'can_print':'print' in caps,'can_create':'create' in caps,'shortcuts':shortcut_catalog(user,store.pk,language),'suggestions':suggestions(user,store.pk,language)})
        return Response({'application':'gestion_magasin','read_only':False,'scope_kind':'store','companies':companies,'languages':['fr','en'],'model':settings.CHAT_AI_MODEL_ID})


class ConversationsView(ChatView):
    def get(self,request):
        serializer=NewConversation(data=request.query_params.dict());serializer.is_valid(raise_exception=True)
        company=serializer.validated_data['company_id'];stamp=authorization_stamp(request.user.pk,company)
        first_message = Message.objects.filter(conversation_id=OuterRef('pk'), role='user').order_by('created_at').values('text')[:1]
        items=Conversation.objects.filter(user=request.user,company_id=company,authorization_stamp=stamp,expires_at__gt=timezone.now()).annotate(title=Substr(Subquery(first_message), 1, 120)).order_by('-updated_at')[:30]
        def readable_title(text):
            try:
                return labelled_text(text or 'Nouvelle conversation', FIELD_LABELS, strict_unknown=False)
            except ChatAIError:
                return 'Conversation'
        return Response([{'id':str(c.pk),'created_at':c.created_at,'updated_at':c.updated_at,'title':readable_title(c.title)} for c in items])

    def post(self,request):
        serializer=NewConversation(data=request.data);serializer.is_valid(raise_exception=True)
        company=serializer.validated_data['company_id'];stamp=authorization_stamp(request.user.pk,company)
        if Conversation.objects.filter(user=request.user,expires_at__gt=timezone.now()).count()>=100:raise ChatAIError('CONTEXT_LIMIT')
        conv=Conversation.objects.create(user=request.user,company_id=company,authorization_stamp=stamp,expires_at=timezone.now()+timedelta(days=settings.CHAT_AI_RETENTION_DAYS))
        return Response({'id':str(conv.pk),'company_id':company},status=201)


class ConversationView(ChatView):
    def get(self,request,id):
        conv=get_conversation(request.user.pk,id);messages=[]
        for m in conv.messages.all()[:60]:
            executor=ChatAIToolExecutor(request.user.pk,conv.company_id,uuid.uuid4(),audit=False)
            payload = replay_message(executor, m)
            messages.append({**payload, 'created_at': m.created_at})
        authorize_delivery(request.user.pk,id,cards=[card for message in messages for card in message['cards']])
        return Response({'id':str(conv.pk),'company_id':conv.company_id,'messages':messages,'results_refreshed':True})

    def delete(self,request,id):
        conv=get_conversation(request.user.pk,id);conv.delete()
        return Response(status=204)


class ChatAIEventStreamRenderer(JSONRenderer):
    # DRF negotiates Accept before post(); successful responses use the async stream.
    media_type = "text/event-stream"
    format = "event-stream"


class MessagesView(ChatView):
    throttle_classes = (ChatInferenceThrottle,)
    renderer_classes = (JSONRenderer, ChatAIEventStreamRenderer)
    def post(self,request,id):
        serializer=NewMessage(data=request.data);serializer.is_valid(raise_exception=True)
        data=serializer.validated_data;get_conversation(request.user.pk,id);validate_text(data['text'])
        user_id=request.user.pk
        cancel=threading.Event()
        if request.headers.get('Accept')!='text/event-stream':
            result=ChatAIConversationService().run(user_id,id,data['text'],data['request_id'],data['context'],lambda *_:None,cancel)
            return Response(result)

        async def events():
            output=queue.Queue(maxsize=256)
            knowledge_sources = None
            def emit(event,payload):
                nonlocal knowledge_sources
                if event == '_knowledge.sources':
                    knowledge_sources = payload['sources']
                    return
                if cancel.is_set():raise ChatAIError('CANCELLED')
                try:output.put_nowait((event,payload))
                except queue.Full:raise ChatAIError('CANCELLED')
            def work():
                try:
                    result=ChatAIConversationService().run(user_id,id,data['text'],data['request_id'],data['context'],emit,cancel)
                    emit('message.completed',result)
                except ChatAIError as exc:
                    if not cancel.is_set():output.put(('error',{'code':exc.code}))
                except Exception:
                    if not cancel.is_set():output.put(('error',{'code':'INTERNAL_ERROR'}))
            worker=asyncio.create_task(asyncio.to_thread(work))
            try:
                yield 'event: message.started\ndata: '+json.dumps({'request_id':str(data['request_id'])})+'\n\n'
                while True:
                    try:event,payload=output.get_nowait()
                    except queue.Empty:
                        if worker.done():break
                        await asyncio.sleep(.05)
                        continue
                    # JWT may expire while inference is running; do not send more private output.
                    expiry=request.auth.get('exp') if request.auth else None
                    if expiry and timezone.now().timestamp()>=expiry:
                        yield 'event: error\ndata: {"code":"NOT_AUTHENTICATED"}\n\n';break
                    try:await sync_to_async(authorize_delivery)(user_id,id,knowledge_sources,payload.get('cards',[]) if event == 'message.completed' else ())
                    except ChatAIError as exc:
                        yield 'event: error\ndata: '+json.dumps({'code':exc.code})+'\n\n';break
                    yield 'event: '+event+'\ndata: '+json.dumps(payload,ensure_ascii=False)+'\n\n'
                    if event in ('message.completed','error'):break
            finally:
                cancel.set()
                # The bounded worker releases its DB lease when upstream exits/timeout fires.
                worker.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
        response=StreamingHttpResponse(events(),content_type='text/event-stream; charset=utf-8')
        response['X-Accel-Buffering']='no'
        return response


class FeedbackView(ChatView):
    def post(self,request):
        serializer=FeedbackInput(data=request.data);serializer.is_valid(raise_exception=True)
        data=serializer.validated_data
        message=Message.objects.filter(pk=data['message_id'],role='assistant',conversation__user=request.user).first()
        if not message:raise ChatAIError('NOT_FOUND')
        get_conversation(request.user.pk,message.conversation_id)
        Feedback.objects.update_or_create(message=message,user=request.user,defaults={'helpful':data['helpful']})
        return Response({'saved':True})


class ConfirmationInput(StrictSerializer):
    confirmed=serializers.BooleanField()


class ConfirmActionView(ChatView):
    throttle_classes = (ChatConfirmationThrottle,)

    def post(self,request,id):
        serializer=ConfirmationInput(data=request.data);serializer.is_valid(raise_exception=True)
        if serializer.validated_data['confirmed'] is not True:raise ChatAIError('INVALID_ARGUMENTS')
        from .actions import confirm
        try:return Response(confirm(request,id))
        except OperationalError as exc:
            if getattr(exc.__cause__,'pgcode',None) in ('57014','55P03'):raise ChatAIError('TOOL_TIMEOUT') from None
            raise


class RecordSelection(StrictSerializer):
    context=Context(default=dict)
    resource=serializers.ChoiceField(choices=[name for name,spec in RESOURCES.items() if spec.editable])
    identifier=serializers.IntegerField(min_value=1)
    operation=serializers.ChoiceField(choices=['edit','delete'])


class RecordSelectionView(ChatView):
    def post(self,request,id):
        conv=get_conversation(request.user.pk,id)
        serializer=RecordSelection(data=request.data);serializer.is_valid(raise_exception=True)
        data=serializer.validated_data
        state=conv.references
        if state.get('resource')!=data['resource'] or data['identifier'] not in state.get('ids',[]) or state.get('expires_at','')<timezone.now().isoformat():raise ChatAIError('CONTEXT_EXPIRED')
        request_id=uuid.uuid4()
        from chat_ai_assistant.clarifications import message_language
        previous=conv.messages.filter(role='user').order_by('-created_at').first()
        language=message_language(previous.text if previous else '',data['context'].get('interface_language','fr'))
        executor=ChatAIToolExecutor(request.user.pk,conv.company_id,request_id,state=state,context={**data['context'],'interface_language':language})
        if data['operation']=='edit':
            from .security import authorize_change
            from .labels import FIELD_LABELS_EN
            obj=executor.record(data['resource'],data['identifier'])
            authorize_change(executor.authorize(),getattr(obj,'store_id',None) or conv.company_id,data['resource'],'update')
            labels=FIELD_LABELS_EN if language=='en' else FIELD_LABELS
            fields=', '.join(labels[field] for field in RESOURCES[data['resource']].editable)
            text=(f'Which field would you like to change ({fields}), and what is the new value? You will review and confirm before it is saved.' if language=='en' else f'Quel champ souhaitez-vous modifier ({fields}) et quelle est la nouvelle valeur ? Vous vérifierez et confirmerez avant l’enregistrement.')
            conv.references={**state,'ids':[data['identifier']],'selected':True,'selection_origin':{key:data['context'][key] for key in ('resource','identifier') if key in data['context']}};conv.save(update_fields=['references','updated_at'])
            Message.objects.create(conversation=conv,role='user',request_id=request_id,text=selected_action_text('edit',data['resource'],language),action={'selected_resource':data['resource'],'selected_identifier':data['identifier'],'selected_operation':'edit','language':language})
            message=Message.objects.create(conversation=conv,role='assistant',request_id=request_id,text=text)
            authorize_delivery(request.user.pk,id)
            return Response({'id':str(message.pk),'role':'assistant','text':text,'cards':[]})
        if data['operation']=='delete':card=executor.execute('prepare_change',{'resource':data['resource'],'identifier':data['identifier'],'operation':'delete'})
        else:card=executor.execute('navigate',{'resource':data['resource']+'_edit','identifier':data['identifier']})
        authorize_delivery(request.user.pk,id,cards=[card])
        Message.objects.create(conversation=conv,role='user',request_id=request_id,text=selected_action_text(data['operation'],data['resource'],language),action={'selected_resource':data['resource'],'selected_identifier':data['identifier'],'selected_operation':data['operation'],'language':language})
        message=Message.objects.create(conversation=conv,role='assistant',request_id=request_id,text='',action=stored_action({'cards':[card]},language))
        return Response({'id':str(message.pk),'role':'assistant','text':'','cards':[card]})


class DocumentInput(NewConversation):
    language=serializers.ChoiceField(choices=['fr','en'])


class DocumentDownloadView(ChatView):
    def get(self,request,id):
        from django.db import transaction
        from sales.models import Sale, Customer
        from sales.views import SaleFacturePdfView
        from rest_framework.test import APIRequestFactory, force_authenticate
        from .security import capabilities
        serializer=DocumentInput(data=request.query_params.dict());serializer.is_valid(raise_exception=True)
        data=serializer.validated_data
        with transaction.atomic():
            user=authorize(request.user.pk,data['company_id'])
            executor=ChatAIToolExecutor(user.pk,data['company_id'],uuid.uuid4())
            executor.record('sale',id)
            obj=Sale.objects.select_for_update().filter(pk=id,store_id=data['company_id']).first()
            if obj is None:raise ChatAIError('NOT_FOUND')
            if obj.customer_id and not Customer.objects.select_for_update().filter(pk=obj.customer_id,store_id=obj.store_id).exists():raise ChatAIError('NOT_FOUND')
            executor.execute('sale_document',{'identifier':obj.pk,'language':data['language']})
            native_request=APIRequestFactory().get('/',{'language':data['language']})
            force_authenticate(native_request,user=user)
            response=SaleFacturePdfView.as_view()(native_request,pk=obj.pk)
            if response.status_code>=400:raise ChatAIError('ACTION_REJECTED')
            if 'print' not in capabilities(authorize(user.pk,data['company_id']),data['company_id']):raise ChatAIError('PERMISSION_DENIED')
        return response
