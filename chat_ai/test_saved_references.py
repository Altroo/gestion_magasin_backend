"""Saved references use fresh native queries; model proposals never execute writes."""
from datetime import date, timedelta, timezone as datetime_timezone
from types import SimpleNamespace
from unittest.mock import patch
import json
import threading
import uuid
import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from chat_ai.models import Conversation, PendingAction
from chat_ai.security import authorization_stamp
from chat_ai.services import ChatAIConversationService, planner_references
from chat_ai.tools import ChatAIToolExecutor
from chat_ai_assistant.contracts import ChatAIError

pytestmark = pytest.mark.django_db


@pytest.fixture
def selection(settings):
    settings.CHAT_AI_ASSISTANT_ENABLED = True
    user = get_user_model().objects.create_user(email='selection@example.invalid', password=None,
        can_view=True, can_edit=True, can_delete=True)
    from store.models import Store, StoreMembership, Role
    from finance.models import Expense, ExpenseCategory
    store = Store.objects.create(code='selection-a', name='Selection A')
    other = Store.objects.create(code='selection-b', name='Selection B')
    role, _ = Role.objects.get_or_create(code='responsable', defaults={'name':'Responsible'})
    StoreMembership.objects.create(user=user, store=store, role=role)
    category = ExpenseCategory.objects.create(code='selection', name='Selection')
    first = Expense.objects.create(store=store, category=category, label='First fixture', amount=10, expense_date=date(2034, 1, 1))
    second = Expense.objects.create(store=store, category=category, label='Second fixture', amount=20, expense_date=date(2034, 1, 2))
    return SimpleNamespace(user=user, first=first, second=second, scope=store.pk, resource='expense', field='label', scope_field='company_id', moved={'store_id':other.pk})


def saved(s, **changes):
    return {'resource':s.resource, 'ids':[s.first.pk, s.second.pk],
            'expires_at':(timezone.now() + timedelta(minutes=5)).isoformat(), **changes}


def conversation(s, **changes):
    return Conversation.objects.create(user=s.user, **{s.scope_field:s.scope},
        authorization_stamp=authorization_stamp(s.user.pk, s.scope),
        expires_at=timezone.now() + timedelta(days=1), references=saved(s, **changes))


def run(s, conv, text, choose, *, context=None, request_id=None):
    with patch('chat_ai.services.close_old_connections'), patch('chat_ai.services.get_model') as model:
        model.return_value.choose.side_effect = choose
        return ChatAIConversationService().run(s.user.pk, conv.pk, text,
            request_id or uuid.uuid4(), context or {}, lambda *_:None, threading.Event())


def trusted(messages):
    return json.loads(messages[0]['content'].split('Trusted context: ', 1)[1])


def action(s, identifier):
    return {'tool':'prepare_change', 'arguments':{'resource':s.resource,
        'identifier':identifier, 'operation':'update', 'changes':{s.field:'Synthetic revision'}}}, {}


@pytest.mark.parametrize('text', ['Update the second result.', 'Modifie le deuxième résultat.'])
@pytest.mark.parametrize('wrong', [False, True])
def test_followup_preserves_display_order_and_rejects_wrong_target(selection, text, wrong):
    s=selection; conv=conversation(s)
    def choose(messages, tools, cancel):
        ctx=trusted(messages)
        assert ctx['previous_result_identifiers']==[s.first.pk,s.second.pk]
        assert ctx['previous_result_type']==s.resource and ctx['previous_result_count']==2
        assert 'prepare_change' in {tool.name for tool in tools}
        return action(s, s.first.pk if wrong else ctx['previous_result_identifiers'][1])
    original=getattr(s.second,s.field)
    # A different current page must not override an explicit result ordinal.
    context={'resource':s.resource,'identifier':s.first.pk}
    if wrong:
        with pytest.raises(ChatAIError) as exc:run(s,conv,text,choose,context=context)
        assert exc.value.code=='CONTEXT_EXPIRED'
        assert not PendingAction.objects.exists()
    else:
        result=run(s,conv,text,choose,context=context)
        assert result['cards'][0]['type']=='confirmation'
        assert result['cards'][0]['record_id']==s.second.pk
    s.second.refresh_from_db()
    assert getattr(s.second,s.field)==original


@pytest.mark.parametrize('cause', ['expired','deleted','moved'])
def test_invalid_complete_selection_clears_without_shifting_ordinals(selection,cause):
    s=selection
    if cause=='moved' and s.moved is None:pytest.skip('This application has no record tenant partition')
    conv=conversation(s)
    if cause=='expired':
        conv.references['expires_at']=(timezone.now()-timedelta(seconds=1)).isoformat();conv.save()
    elif cause=='deleted':s.first.delete()
    else:type(s.first).objects.filter(pk=s.first.pk).update(**s.moved)
    def choose(messages,tools,cancel):
        ctx=trusted(messages)
        assert ctx['previous_result_identifiers']==[]
        assert ctx['previous_result_type'] is None and ctx['previous_result_count']==0
        assert 'previous_results' not in {tool.name for tool in tools}
        return {'tool':'clarify','message':'Please search again.'},{}
    run(s,conv,'Update the second result.',choose)
    conv.refresh_from_db();assert conv.references=={}
    assert not PendingAction.objects.exists()


@pytest.mark.parametrize('changes', [
    {'resource':'other_app'}, {'resource':{}}, {'ids':[True]}, {'ids':['1']},
    {'ids':[1,1]}, {'ids':list(range(1,12))}, {'ids':[-1]}, {'ids':[2147483648]},
    {'expires_at':None}, {'expires_at':'invalid'}, {'expires_at':'2099-01-01T00:00:00'},
])
def test_malformed_references_never_reach_queries(selection,changes):
    s=selection;executor=ChatAIToolExecutor(s.user.pk,s.scope,uuid.uuid4(),state=saved(s,**changes))
    with patch.object(executor,'read_records') as read:
        assert planner_references(executor)=={}
        read.assert_not_called()
    assert executor.state=={}


def test_reference_timezone_offsets_are_normalized(selection):
    s=selection
    expires=(timezone.now()+timedelta(minutes=5)).astimezone(datetime_timezone(timedelta(hours=-5)))
    executor=ChatAIToolExecutor(s.user.pk,s.scope,uuid.uuid4(),state=saved(s,expires_at=expires.isoformat()))
    assert planner_references(executor)['ids']==[s.first.pk,s.second.pk]
    assert executor.state['expires_at'].endswith('+00:00')


@pytest.mark.parametrize('before', [True,False])
def test_permission_revocation_before_or_during_planning(selection,before):
    s=selection;conv=conversation(s)
    if before:get_user_model().objects.filter(pk=s.user.pk).update(can_view=False)
    def choose(messages,tools,cancel):
        assert not before, 'Revoked identity must not reach inference'
        get_user_model().objects.filter(pk=s.user.pk).update(can_edit=False)
        return action(s,trusted(messages)['previous_result_identifiers'][1])
    with pytest.raises(ChatAIError) as exc:run(s,conv,'Update the second result.',choose)
    assert exc.value.code in ('PERMISSION_DENIED','CONTEXT_EXPIRED')
    assert not PendingAction.objects.exists()


@pytest.mark.parametrize('operation', ['list','open'])
def test_record_removed_during_planning_cannot_shift_result_indices(selection,operation):
    s=selection;conv=conversation(s)
    def choose(messages,tools,cancel):
        assert trusted(messages)['previous_result_identifiers']==[s.first.pk,s.second.pk]
        s.first.delete()
        return {'tool':'previous_results','arguments':{'operation':operation,**({'index':2} if operation=='open' else {})}},{}
    with pytest.raises(ChatAIError) as exc:run(s,conv,'Use the previous results please.',choose)
    assert exc.value.code=='CONTEXT_EXPIRED'


@pytest.mark.parametrize('new_request', [False,True])
def test_inline_selection_preserves_retry_binding_and_is_consumed(selection,new_request):
    s=selection;origin={'resource':s.resource,'identifier':s.second.pk}
    conv=conversation(s,ids=[s.first.pk],selected=True,selection_origin=origin)
    request_id=uuid.uuid4();seen=[]
    def choose(messages,tools,cancel):
        ctx=trusted(messages);seen.append(ctx)
        target=s.second.pk if new_request and len(seen)==2 else s.first.pk
        assert ctx['current_resource']==s.resource and ctx['current_identifier']==target
        if len(seen)==1:raise RuntimeError('Synthetic inference failure')
        return action(s,target)
    with pytest.raises(RuntimeError):
        run(s,conv,'Update this record.',choose,context=origin,request_id=request_id)
    conv.refresh_from_db();assert conv.references['selection_request_id']==str(request_id)
    result=run(s,conv,'Update this record.',choose,context=origin,request_id=uuid.uuid4() if new_request else request_id)
    assert result['cards'][0]['record_id']==(s.second.pk if new_request else s.first.pk)
    conv.refresh_from_db()
    assert not any(key in conv.references for key in ('selected','selection_origin','selection_request_id'))
