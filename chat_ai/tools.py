"""Bounded native tools: identity, store, role and object checks run in backend code."""
from datetime import date, timedelta
from types import SimpleNamespace
import time
from django.conf import settings
from django.db import connection, transaction, OperationalError
from django.db.models import Q, F, Value
from django.db.models.functions import Coalesce
from django.http import QueryDict
from django.utils import timezone
from chat_ai_assistant.contracts import ChatAIError, ChatAITool, ChatAIToolRegistry, object_schema, ID, STRING
from store.models import Store
from store.permissions import user_store_ids, user_has_store_access, MANAGEMENT_ROLES
from stock.filters import StockBalanceFilter
from attendance.views import _is_mbr_south_scope
from .security import authorize, capabilities, authorize_resource, authorize_change, vendeur_only, flag
from .resources import RESOURCES
from .models import AuditEvent
from .navigation import ChatAINavigationResolver, ROUTES, DETAILS, EDIT_FORMS, FORM_NEW, LIST_RESOURCE
from .knowledge import ChatAIKnowledgeService
from .labels import FIELD_LABELS, FIELD_LABELS_EN

RESOURCE = {'type':'string','enum':list(RESOURCES)}
DATE = {'type':'string','pattern':r'^\d{4}-\d{2}-\d{2}$'}
METRICS = {
 'sales_total': ('Ventes confirmées', 'Confirmed sales', 'Total des ventes confirmées sur la période.', 'Total of confirmed sales in this period.'),
 'expenses_total': ('Dépenses', 'Expenses', 'Dépenses enregistrées sur la période, tous statuts de paiement.', 'Recorded expenses in this period, all payment statuses.'),
 'purchases_total': ('Achats réceptionnés', 'Received purchases', 'Sous-total des achats réceptionnés sur la période.', 'Subtotal of received purchases in this period.'),
 'net_total': ('Solde du tableau de bord', 'Dashboard balance', 'Ventes moins dépenses et achats réceptionnés ; ce montant ne représente pas un bénéfice comptable.', 'Sales minus expenses and received purchases; this is not accounting profit.'),
 'stock_value_total': ('Valeur du stock actuel', 'Current stock value', 'Quantités actuelles multipliées par le coût moyen ; ne dépend pas de la période.', 'Current quantities multiplied by average cost; independent of the date period.'),
 'today_cash_total': ('Montants payés aujourd’hui', 'Amounts paid today', 'Montants payés des ventes confirmées et marquées payées aujourd’hui, tous modes de paiement.', 'Paid amounts of confirmed sales marked paid today, all payment modes.'),
 'sales_count': ('Nombre de ventes confirmées', 'Confirmed sale count', 'Ventes confirmées sur la période.', 'Confirmed sales in this period.'),
}


def registry():
    search = object_schema({'resource':RESOURCE,'query':STRING,'product_name':STRING,'customer_name':STRING,'employee_name':STRING,'status':STRING,'date_from':DATE,'date_to':DATE,'low_stock':{'type':'boolean'},'limit':{'type':'integer','minimum':1,'maximum':10},'offset':{'type':'integer','minimum':0,'maximum':100}},['resource'])
    writable = [name for name,spec in RESOURCES.items() if spec.editable]
    specs = [
      ('search_records','Find permitted articles, stock, sales, customers, expenses, purchases, transfers, inventories, promotions, attendance, employees, stock requests, stores or users. Search descriptions, not guessed IDs. Filters combine with AND.',search,('read',)),
      ('get_record','Read a known internal identifier or the current page after native detail authorization.',object_schema({'resource':RESOURCE,'identifier':ID},['resource']),('read',)),
      ('navigate','Open an approved native page or known record/form. Never invent URLs.',object_schema({'resource':{'type':'string','enum':list(ROUTES)+list(DETAILS)+[x+'_edit' for x in sorted(EDIT_FORMS)]+[x+'_new' for x in sorted(FORM_NEW)]},'identifier':ID},['resource']),('read',)),
      ('financial_summary','Read one native staff-only dashboard metric for the selected store. Explicit dates required; stock value is current and amounts paid today are today only. Never treat dashboard balance as accounting profit.',object_schema({'metric':{'type':'string','enum':list(METRICS)},'date_from':DATE,'date_to':DATE},['metric','date_from','date_to']),('read','financial')),
      ('knowledge','Retrieve verified, permission-filtered application procedures.',object_schema({'query':STRING},['query']),('read',)),
      ('previous_results','List saved authorized results or open one by its one-based index.',object_schema({'operation':{'type':'string','enum':['open','list']},'index':{'type':'integer','minimum':1,'maximum':10}},['operation']),('read',)),
      ('sale_document','Offer the native invoice PDF for a known authorized WHOLESALE sale; separate from POS receipts.',object_schema({'identifier':ID,'language':{'type':'string','enum':['fr','en']}},['identifier','language']),('read','print','read_sale')),
      ('prepare_change','Propose a supported known-record edit or deletion for separate exact-target confirmation. Financial values, stock movements, relationship changes and sale deletion/voiding are unsupported.',object_schema({'resource':{'type':'string','enum':writable},'identifier':ID,'operation':{'type':'string','enum':['update','delete']},'changes':{'type':'object','maxProperties':8,'propertyNames':{'enum':sorted({f for s in RESOURCES.values() for f in s.editable})},'additionalProperties':{'type':['string','null'],'maxLength':1000}}},['resource','identifier','operation']),('read',)),
    ]
    return ChatAIToolRegistry([ChatAITool(name,description,schema,{'type':'object'},name,application='gestion_magasin',required_capabilities=caps,authorization='fresh native user flags, module gates, store roles and object scope',classification='proposal' if name=='prepare_change' else 'read',audit_classification='business_proposal' if name=='prepare_change' else 'business_read') for name,description,schema,caps in specs])


def native_request(user, store_id, **filters):
    params = QueryDict('', mutable=True)
    params['store'] = str(store_id)
    for key,value in filters.items():
        if value not in ('',None):params[key]=str(value)
    return SimpleNamespace(user=user,query_params=params,data={},method='GET')


class ChatAIToolExecutor:
    def __init__(self,user_id,company_id,request_id,state=None,context=None,audit=True,instruction=None):
        self.user_id,self.company_id,self.request_id=user_id,company_id,request_id
        self.state,self.context=state or {},context or {}
        self.audit,self.instruction=audit,instruction

    def authorize(self):return authorize(self.user_id,self.company_id)
    authorize_context=authorize
    def capabilities(self):return capabilities(self.authorize(),self.company_id)
    def output_labels(self):return FIELD_LABELS_EN if self.context.get('interface_language')=='en' else FIELD_LABELS

    def authorize_knowledge(self,documents):
        sources=[{'document_id':d['document_id'],'version':d['version']} for d in documents]
        if not ChatAIKnowledgeService.sources_authorized(sources,self.company_id,self.capabilities()):raise ChatAIError('CONTEXT_EXPIRED')

    def execute(self,name,arguments):
        started,outcome=time.monotonic(),'denied'
        try:
            self.authorize();tool=registry().validate(name,arguments)
            if not set(tool.required_capabilities)<=self.capabilities():raise ChatAIError('PERMISSION_DENIED')
            try:
                with transaction.atomic():
                    if connection.vendor=='postgresql':
                        with connection.cursor() as cursor:cursor.execute('SET LOCAL statement_timeout = %s',[tool.timeout_seconds*1000])
                    result=getattr(self,name)(**arguments)
                    if time.monotonic()-started>tool.timeout_seconds:raise ChatAIError('TOOL_TIMEOUT')
                    self.authorize()
            except OperationalError as exc:
                if getattr(exc.__cause__,'pgcode',None) in ('57014','55P03'):raise ChatAIError('TOOL_TIMEOUT') from None
                raise
            outcome='allowed';return result
        finally:
            if self.audit:AuditEvent.objects.create(user_id=self.user_id,actor_id=self.user_id,company_id=self.company_id,application='gestion_magasin',tool=name[:64],outcome=outcome,correlation_id=self.request_id,model_version=settings.CHAT_AI_MODEL_ID,duration_ms=max(0,int((time.monotonic()-started)*1000)))

    def queryset(self,resource,query=''):
        user=self.authorize()
        if resource not in RESOURCES:raise ChatAIError('INVALID_ARGUMENTS')
        authorize_resource(user,self.company_id,resource)
        spec=RESOURCES[resource];request=native_request(user,self.company_id,search=query)
        if spec.queryset:
            qs=spec.queryset(request)
            if resource=='stock':qs=StockBalanceFilter(request.query_params,queryset=qs).qs
        else:
            qs=spec.model.objects.all()
            if query:
                match=Q()
                for field in (('first_name','last_name','email') if resource=='user' else ('name','code')):match|=Q(**{field+'__icontains':query})
                qs=qs.filter(match)
        expanded=resource in ('attendance','employee') and _is_mbr_south_scope(request)
        if spec.scope_field and not expanded:qs=qs.filter(**{spec.scope_field:self.company_id})
        # Native generic filters also search related names. A malformed relation
        # must not disclose that name through a match/count even if projection hides it.
        if query and resource=='sale':qs=qs.filter(Q(customer__isnull=True)|Q(customer__store_id=F('store_id')))
        if query and resource=='attendance':qs=qs.filter(employee__store_id=F('store_id'))
        return qs

    def detail_queryset(self,resource):
        qs=self.queryset(resource)
        # Native attendance list expansion does not authorize detail or mutation.
        if resource=='attendance' and not self.authorize().is_staff:
            qs=qs.filter(store_id__in=user_store_ids(self.authorize()))
        return qs

    def record(self,resource,identifier):
        if type(identifier) is not int or not 0<identifier<=2147483647:raise ChatAIError('INVALID_ARGUMENTS')
        obj=self.detail_queryset(resource).filter(pk=identifier).first()
        if obj is None:raise ChatAIError('NOT_FOUND')
        return obj

    def serialize(self,resource,obj):
        en=self.context.get('interface_language')=='en';user=self.authorize()
        def detail(fr,enlabel,value):return {'label':fr,'label_en':enlabel,'value':str(value)}
        item={'id':obj.pk,'details':[]}
        if resource=='product':
            item.update(name=obj.name[:255],reference=obj.reference or '',description=obj.barcode or '')
            item['details']=[detail('Prix détail','Retail price',str(obj.detail_price)+' MAD'),detail('Prix comptoir','Counter price',str(obj.counter_price)+' MAD')]
        elif resource=='stock':
            item.update(name=obj.product.name[:255],quantity=str(obj.quantity),status=(('Low stock' if en else 'Stock faible') if obj.is_low_stock else ('Stock available' if en else 'Stock disponible')))
            item['details']=[detail('Stock minimum','Minimum stock',obj.effective_min_stock),detail('Coût moyen','Average cost',str(obj.average_cost)+' MAD')]
        elif resource=='sale':
            item.update(name=('Sale' if en else 'Vente')+' #'+str(obj.pk),amount=str(obj.total),currency='MAD',date=timezone.localtime(obj.date_created).date().isoformat(),status=obj.status)
            if obj.customer_id and obj.customer.store_id==obj.store_id:item['client']=obj.customer.full_name[:160]
            item['details']=[{**detail('Statut paiement','Payment status',obj.get_payment_status_display()),'status_code':obj.payment_status}]
            item['can_print']='print' in self.capabilities() and obj.sale_type=='wholesale' and (not obj.customer_id or obj.customer.store_id==obj.store_id)
        elif resource=='customer':item.update(name=obj.full_name[:160],description=(obj.phone or '')[:40])
        elif resource=='expense':item.update(name=obj.label[:180],amount=str(obj.amount),currency='MAD',date=obj.expense_date.isoformat(),status=obj.payment_status)
        elif resource=='purchase':item.update(name=obj.reference or ('Purchase' if en else 'Achat')+' #'+str(obj.pk),supplier=obj.supplier_name[:160],amount=str(obj.subtotal),currency='MAD',date=obj.purchase_date.isoformat(),status=obj.status)
        elif resource=='transfer':item.update(name=obj.reference or ('Transfer' if en else 'Transfert')+' #'+str(obj.pk),date=obj.transfer_date.isoformat(),status=obj.status)
        elif resource=='inventory':item.update(name=(obj.title or obj.code)[:255],date=obj.inventory_date.isoformat(),status=obj.status)
        elif resource=='promotion':item.update(name=obj.name[:160],amount=str(obj.selling_price),currency='MAD',status=obj.status)
        elif resource=='attendance':
            item.update(name=obj.employee.full_name[:200] if obj.employee.store_id==obj.store_id else ('Attendance' if en else 'Pointage')+' #'+str(obj.pk),date=obj.date.isoformat(),status=obj.status)
            item['details']=[detail('Heures travaillées','Hours worked',obj.hours_worked),detail('Retard (minutes)','Delay (minutes)',obj.delay_minutes)]
        elif resource=='employee':item.update(name=obj.full_name[:200],description=obj.position[:200])
        elif resource=='stock_request':item.update(name=obj.product.name[:255],quantity=str(obj.quantity),status=obj.status)
        elif resource=='store':item.update(name=obj.name[:160])
        else:item.update(name=(' '.join(filter(None,[obj.first_name,obj.last_name])))[:200] or ('User' if en else 'Utilisateur'),status=('Active' if en else 'Actif') if obj.is_active else ('Inactive' if en else 'Inactif'))
        detail_allowed=self.detail_queryset(resource).filter(pk=obj.pk).exists()
        if resource in DETAILS and detail_allowed:item['navigation']=ChatAINavigationResolver.resolve(resource,self.company_id,obj.pk)
        spec=RESOURCES[resource]
        if spec.editable and detail_allowed:
            try:authorize_change(user,getattr(obj,'store_id',None) or self.company_id,resource,'update');item['can_update']=True
            except ChatAIError:item['can_update']=False
            try:
                authorize_change(user,getattr(obj,'store_id',None) or self.company_id,resource,'delete')
                item['can_delete']=spec.deletable
            except ChatAIError:item['can_delete']=False
        return item

    def read_records(self,resource,ids):
        if not isinstance(ids,list) or len(ids)>10 or any(type(i)is not int or i<1 for i in ids):raise ChatAIError('INVALID_ARGUMENTS')
        qs=self.queryset(resource).filter(pk__in=ids)
        # Replayed/delivered searches must not reveal a formerly matching name
        # through record presence after that relation leaves its native store.
        if resource=='sale':qs=qs.filter(Q(customer__isnull=True)|Q(customer__store_id=F('store_id')))
        if resource=='attendance':qs=qs.filter(employee__store_id=F('store_id'))
        objects={obj.pk:obj for obj in qs}
        return [self.serialize(resource,objects[i]) for i in ids if i in objects]

    @staticmethod
    def dates(date_from,date_to):
        try:start=date.fromisoformat(date_from) if date_from else None;end=date.fromisoformat(date_to) if date_to else None
        except ValueError:raise ChatAIError('INVALID_ARGUMENTS') from None
        if start and end and start>end:raise ChatAIError('INVALID_ARGUMENTS')
        return start,end

    def search_records(self,resource,query='',product_name='',customer_name='',employee_name='',status='',date_from=None,date_to=None,low_stock=None,limit=10,offset=0):
        qs=self.queryset(resource,query);spec=RESOURCES[resource]
        start,end=self.dates(date_from,date_to)
        if start or end:
            if not spec.date_field:raise ChatAIError('INVALID_ARGUMENTS')
            if start:qs=qs.filter(**{spec.date_field+'__gte':start})
            if end:qs=qs.filter(**{spec.date_field+'__lte':end})
        if product_name:
            field={'product':'name','stock':'product__name','stock_request':'product__name','sale':'lines__product__name','purchase':'lines__product__name','transfer':'lines__product__name','inventory':'lines__product__name','promotion':'lines__product__name'}.get(resource)
            if not field:raise ChatAIError('INVALID_ARGUMENTS')
            qs=qs.filter(**{field+'__icontains':product_name})
        if customer_name:
            if resource!='sale':raise ChatAIError('INVALID_ARGUMENTS')
            qs=qs.filter(customer__store_id=F('store_id'),customer__full_name__icontains=customer_name)
        if employee_name:
            if resource!='attendance':raise ChatAIError('INVALID_ARGUMENTS')
            qs=qs.filter(employee__store_id=F('store_id'),employee__full_name__icontains=employee_name)
        if status:
            field='payment_status' if resource=='expense' else 'status'
            try:choices=dict(spec.model._meta.get_field(field).choices)
            except Exception:raise ChatAIError('INVALID_ARGUMENTS') from None
            if status not in choices:raise ChatAIError('INVALID_ARGUMENTS')
            qs=qs.filter(**{field:status})
        if low_stock is not None:
            if resource!='stock':raise ChatAIError('INVALID_ARGUMENTS')
            qs=qs.annotate(_minimum=Coalesce('min_stock','product__default_stock_alert'))
            condition=Q(_minimum__gt=0,quantity__lte=F('_minimum'))
            qs=qs.filter(condition if low_stock else ~condition)
        found=list(qs.distinct().order_by('-pk')[offset:offset+limit+1])
        items=[self.serialize(resource,obj) for obj in found[:limit]]
        self.state={'resource':resource,'ids':[i['id'] for i in items],'expires_at':(timezone.now()+timedelta(minutes=20)).isoformat()}
        return {'type':'record_list','language':self.context.get('interface_language','fr'),'resource':resource,'items':items,'has_more':len(found)>limit}

    def get_record(self,resource,identifier=None):
        if identifier is None:
            if self.context.get('resource')!=resource:raise ChatAIError('INVALID_ARGUMENTS')
            identifier=self.context.get('identifier')
        obj=self.record(resource,identifier)
        self.state={'resource':resource,'ids':[obj.pk],'expires_at':(timezone.now()+timedelta(minutes=20)).isoformat()}
        return {'type':'record_list','language':self.context.get('interface_language','fr'),'resource':resource,'items':[self.serialize(resource,obj)]}

    def navigate(self,resource,identifier=None):
        user=self.authorize();caps=self.capabilities();base=resource.removesuffix('_new').removesuffix('_edit')
        if resource in ('dashboard','store_stock') and 'financial' not in caps:raise ChatAIError('PERMISSION_DENIED')
        if resource=='pos':
            if 'pos_access' not in caps:raise ChatAIError('PERMISSION_DENIED')
        elif resource in ('promotion_new','promotion_edit'):
            if 'promotion_form' not in caps:raise ChatAIError('PERMISSION_DENIED')
        else:authorize_resource(user,self.company_id,LIST_RESOURCE.get(base,base)) if base!='dashboard' else None
        if resource.endswith('_new') or resource.endswith('_edit'):
            needed='update' if resource.endswith('_edit') else 'create'
            # Inventory/expense/transfer form screens use the native create gate in both modes.
            if base in ('inventory','expense','transfer'):needed='create'
            if base=='promotion':
                if not flag(user,'create_promotion'):raise ChatAIError('PERMISSION_DENIED')
            elif needed not in caps:raise ChatAIError('PERMISSION_DENIED')
            if resource=='promotion_edit':
                qs=RESOURCES['promotion'].queryset(native_request(user,self.company_id)).filter(store_id=self.company_id)
                if type(identifier)is not int or not qs.filter(pk=identifier).exists():raise ChatAIError('NOT_FOUND')
            elif resource.endswith('_edit'):self.record(base,identifier)
        elif base in DETAILS:self.record(base,identifier)
        return {'type':'navigation','target':ChatAINavigationResolver.resolve(resource,self.company_id,identifier)}

    def previous_results(self,operation,index=None):
        if not self.state.get('ids') or self.state.get('expires_at','')<timezone.now().isoformat():raise ChatAIError('CONTEXT_EXPIRED')
        items=self.read_records(self.state['resource'],self.state['ids'])
        if len(items)!=len(self.state['ids']):raise ChatAIError('CONTEXT_EXPIRED')
        if operation=='list':return {'type':'record_list','language':self.context.get('interface_language','fr'),'resource':self.state['resource'],'items':items}
        if index is None or index>len(items) or not items[index-1].get('navigation'):raise ChatAIError('INVALID_ARGUMENTS')
        target=items[index-1]['navigation'];return self.navigate(target['resource'],target['identifier'])

    def financial_summary(self,metric,date_from,date_to):
        if 'financial' not in self.capabilities():raise ChatAIError('PERMISSION_DENIED')
        start,end=self.dates(date_from,date_to)
        if not start or not end or (end-start).days>366:raise ChatAIError('INVALID_ARGUMENTS')
        if metric in ('stock_value_total','today_cash_total') and (start!=timezone.localdate() or end!=timezone.localdate()):raise ChatAIError('INVALID_ARGUMENTS')
        from reporting.views import StoreDashboardReportView
        response=StoreDashboardReportView.get(native_request(self.authorize(),self.company_id,date_from=start.isoformat(),date_to=end.isoformat()))
        if response.status_code!=200:raise ChatAIError('APPLICATION_UNAVAILABLE')
        fr,en,definition,definition_en=METRICS[metric]
        return {'type':'financial_summary','metric':metric,'label':fr,'label_en':en,'value':str(response.data['kpis'][metric]),'currency':None if metric=='sales_count' else 'MAD','period':{'date_from':start.isoformat(),'date_to':end.isoformat()},'as_of':timezone.localdate().isoformat(),'definition':definition,'definition_en':definition_en}

    def knowledge(self,query):return {'type':'knowledge','documents':ChatAIKnowledgeService().retrieve(query,self.company_id,self.capabilities())}

    def sale_document(self,identifier,language):
        if 'print' not in self.capabilities():raise ChatAIError('PERMISSION_DENIED')
        obj=self.record('sale',identifier)
        if obj.sale_type!='wholesale' or (obj.customer_id and obj.customer.store_id!=obj.store_id):raise ChatAIError('NOT_FOUND')
        return {'type':'pdf','resource':'sale','record_id':obj.pk,'number':str(obj.pk),'format':'pdf','language':language}

    def prepare_change(self,resource,identifier,operation,changes=None):
        from .actions import prepare
        return prepare(self,resource,identifier,operation,changes or {})
