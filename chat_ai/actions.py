"""Native writes require an owned, unexpired, exact-target confirmation and fresh locks."""
from contextlib import contextmanager
from datetime import timedelta
import hashlib
import json
from django.conf import settings
from django.db import transaction, connection, OperationalError
from django.db.models.deletion import ProtectedError, RestrictedError
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models.fields.files import FieldFile
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate
from simple_history.models import HistoricalRecords
from account.models import CustomUser
from store.models import Store, StoreMembership, Role
from chat_ai_assistant.contracts import ChatAIError
from .models import PendingAction, AuditEvent
from .resources import RESOURCES
from .security import authorize, authorize_change, validate_text
from .labels import FIELD_LABELS, FIELD_LABELS_EN


def fingerprint(obj):
    values={field.attname:getattr(obj,field.attname) for field in obj._meta.concrete_fields}
    values={key:(value.name if isinstance(value,FieldFile) else value) for key,value in values.items()}
    return hashlib.sha256(json.dumps(values,sort_keys=True,cls=DjangoJSONEncoder).encode()).hexdigest()


def native_context(user, store_id):
    from .tools import native_request
    return {'request':native_request(user,store_id),'store_id':store_id}


def validated_update(resource,obj,changes,user,store_id):
    spec=RESOURCES[resource]
    if not changes or set(changes)-set(spec.editable):raise ChatAIError('INVALID_ARGUMENTS')
    for value in changes.values():
        if value is not None:
            if not isinstance(value,str) or len(value)>1000:raise ChatAIError('INVALID_ARGUMENTS')
            if value.strip():validate_text(value)
    serializer=spec.serializer(obj,data=changes,partial=True,context=native_context(user,store_id))
    if not serializer.is_valid():raise ChatAIError('INVALID_ARGUMENTS')
    return dict(changes)


def ensure_delete_scope(resource,obj):
    if not RESOURCES[resource].deletable:raise ChatAIError('ACTION_REJECTED')
    if resource in ('product','customer'):
        # Global product deletion may cascade stock or detach customer sales.
        # Such dependencies need a richer native review; this adapter never hides them.
        for relation in obj._meta.related_objects:
            if relation.one_to_many and relation.related_model.objects.filter(**{relation.field.name:obj}).exists():
                raise ChatAIError('ACTION_REJECTED')


def checked_object(executor,resource,identifier,operation,changes):
    if resource not in RESOURCES or not RESOURCES[resource].editable:raise ChatAIError('INVALID_ARGUMENTS')
    obj=executor.record(resource,identifier)
    if resource=='attendance' and obj.employee.store_id!=obj.store_id:raise ChatAIError('NOT_FOUND')
    if resource=='sale' and obj.customer_id and obj.customer.store_id!=obj.store_id:raise ChatAIError('NOT_FOUND')
    user=executor.authorize();store_id=getattr(obj,'store_id',None) or executor.company_id
    authorize_change(user,store_id,resource,operation)
    if operation=='delete':
        if changes:raise ChatAIError('INVALID_ARGUMENTS')
        ensure_delete_scope(resource,obj)
    elif operation=='update':validated_update(resource,obj,changes,user,store_id)
    else:raise ChatAIError('INVALID_ARGUMENTS')
    return obj


def confirmation_card(action,obj,language='fr'):
    en=language=='en'
    return {'type':'confirmation','action_id':str(action.pk),'company_id':action.company_id,'resource':action.resource,'record_id':action.record_id,'operation':action.operation,'label':(('Attendance' if en else 'Pointage')+' #'+str(obj.pk)) if action.resource=='attendance' else str(obj)[:300],'changes':action.changes,'before':{key:str(getattr(obj,key)) if getattr(obj,key)is not None else None for key in action.changes},'warning':'This action will be recorded under your identity.' if en else 'Cette action sera enregistrée sous votre identité.'}


def prepare(executor,resource,identifier,operation,changes):
    from .targets import trusted_target
    if not trusted_target(resource,identifier,instruction=executor.instruction or '',context=executor.context,state=executor.state,now=timezone.now()):raise ChatAIError('CONTEXT_EXPIRED')
    obj=checked_object(executor,resource,identifier,operation,changes)
    if PendingAction.objects.filter(user_id=executor.user_id,consumed_at__isnull=True,expires_at__gt=timezone.now()).count()>=20:raise ChatAIError('CONTEXT_LIMIT')
    action=PendingAction.objects.create(user_id=executor.user_id,company_id=executor.company_id,resource=resource,record_id=obj.pk,operation=operation,changes=changes,fingerprint=fingerprint(obj),expires_at=timezone.now()+timedelta(minutes=5),instruction_id=executor.request_id)
    return confirmation_card(action,obj,executor.context.get('interface_language','fr'))


def replay_confirmation(executor,action):
    en=action.get('language')=='en'
    done='Action already performed under your identity.' if en else 'Action déjà effectuée sous votre identité.'
    pending=PendingAction.objects.filter(pk=action['confirmation_id'],user_id=executor.user_id,company_id=executor.company_id).first()
    if pending is None:
        exists=AuditEvent.objects.filter(correlation_id=action['confirmation_id'],actor_id=executor.user_id,company_id=executor.company_id,application='gestion_magasin',tool__startswith='confirmed_',outcome='allowed').exists()
        return {'type':'confirmation_status','message':done if exists else ('Action unavailable.' if en else 'Action indisponible.')}
    if pending.consumed_at:return {'type':'confirmation_status','message':done}
    if pending.expires_at<=timezone.now():return {'type':'confirmation_status','message':'This confirmation has expired.' if en else 'Cette confirmation a expiré.'}
    obj=checked_object(executor,pending.resource,pending.record_id,pending.operation,pending.changes)
    if fingerprint(obj)!=pending.fingerprint:raise ChatAIError('CONTEXT_EXPIRED')
    return confirmation_card(pending,obj,'en' if en else 'fr')


@contextmanager
def native_history_request(request):
    missing=object();previous=getattr(HistoricalRecords.context,'request',missing)
    HistoricalRecords.context.request=request
    try:yield
    finally:
        if previous is missing:del HistoricalRecords.context.request
        else:HistoricalRecords.context.request=previous


def lock_authorization(user_id,store_id):
    # Parent locks also block concurrent membership insertion/removal at this boundary.
    if not CustomUser.objects.select_for_update().filter(pk=user_id).exists():raise ChatAIError('NOT_AUTHENTICATED')
    list(Store.objects.select_for_update().filter(pk=store_id).values_list('pk',flat=True))
    memberships=list(StoreMembership.objects.select_for_update().filter(user_id=user_id).values_list('role_id',flat=True))
    list(Role.objects.select_for_update().filter(pk__in=memberships).values_list('pk',flat=True))


def confirm(request,id):
    from .tools import ChatAIToolExecutor
    with transaction.atomic():
        if connection.vendor=='postgresql':
            with connection.cursor() as cursor:
                cursor.execute('SET LOCAL lock_timeout = %s',[5000]);cursor.execute('SET LOCAL statement_timeout = %s',[5000])
        action=PendingAction.objects.select_for_update().filter(pk=id,user=request.user).first()
        if action is None:raise ChatAIError('NOT_FOUND')
        user=authorize(request.user.pk,action.company_id)
        if action.consumed_at or action.expires_at<=timezone.now():raise ChatAIError('CONTEXT_EXPIRED')
        spec=RESOURCES[action.resource]
        # Lock the target before dependency validation; FK insertion must wait.
        obj=spec.model.objects.select_for_update().filter(pk=action.record_id).first()
        if obj is None:raise ChatAIError('CONTEXT_EXPIRED')
        if action.resource=='attendance':
            from attendance.models import Employee
            list(Employee.objects.select_for_update().filter(pk=obj.employee_id).values_list('pk',flat=True))
        if action.resource=='sale' and obj.customer_id:
            from sales.models import Customer
            list(Customer.objects.select_for_update().filter(pk=obj.customer_id).values_list('pk',flat=True))
        store_id=getattr(obj,'store_id',None) or action.company_id
        lock_authorization(user.pk,store_id)
        if store_id!=action.company_id:list(Store.objects.select_for_update().filter(pk=action.company_id).values_list('pk',flat=True))
        user=authorize(user.pk,action.company_id)
        executor=ChatAIToolExecutor(user.pk,action.company_id,action.pk,audit=False)
        obj=checked_object(executor,action.resource,obj.pk,action.operation,action.changes)
        if action.expires_at<=timezone.now() or fingerprint(obj)!=action.fingerprint:raise ChatAIError('CONTEXT_EXPIRED')
        data=validated_update(action.resource,obj,action.changes,user,store_id) if action.operation=='update' else None
        factory=APIRequestFactory();path='/?store='+str(store_id)
        native_request=factory.patch(path,data,format='json') if data is not None else factory.delete(path)
        force_authenticate(native_request,user=user)
        with native_history_request(request):
            try:response=spec.view.as_view()(native_request,pk=obj.pk)
            except (ProtectedError,RestrictedError):raise ChatAIError('ACTION_REJECTED') from None
        if response.status_code>=400:raise ChatAIError('ACTION_REJECTED')
        action.consumed_at=timezone.now();action.save(update_fields=['consumed_at'])
        AuditEvent.objects.create(user=user,actor_id=user.pk,actor_label=str(user)[:254],application='gestion_magasin',company_id=action.company_id,resource=action.resource,record_id=action.record_id,changed_fields=sorted(action.changes),tool='confirmed_'+action.operation,outcome='allowed',instruction_id=action.instruction_id,correlation_id=action.pk,model_version=settings.CHAT_AI_MODEL_ID)
    return {'success':True,'operation':action.operation,'resource':action.resource,'record_id':action.record_id}
