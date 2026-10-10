"""Only native routes; scope is a validated backend Store identifier."""
from chat_ai_assistant.contracts import ChatAIError
ROUTES = {'dashboard':'', 'products':'article', 'stock_list':'stock', 'store_stock':'store-stock', 'sales':'sales', 'purchases':'purchases', 'transfers':'stock-transfers', 'inventories':'inventory', 'expenses':'expenses', 'promotions':'promotions', 'attendance_list':'pointage', 'stores':'stores', 'users':'users', 'pos':'caise'}
DETAILS = {'product':'article', 'stock':'stock', 'sale':'sales', 'purchase':'purchases', 'transfer':'stock-transfers', 'inventory':'inventory', 'expense':'expenses', 'promotion':'promotions', 'attendance':'pointage', 'store':'stores', 'user':'users'}
EDIT_FORMS = set(DETAILS) - {'sale'}
FORM_NEW = set(DETAILS)
LIST_RESOURCE = {'products':'product','stock_list':'stock','store_stock':'stock','sales':'sale','purchases':'purchase','transfers':'transfer','inventories':'inventory','expenses':'expense','promotions':'promotion','attendance_list':'attendance','stores':'store','users':'user'}

class ChatAINavigationResolver:
    @staticmethod
    def resolve(resource, company_id, identifier=None):
        if type(company_id) is not int or company_id < 1:
            raise ChatAIError('INVALID_ARGUMENTS')
        base, suffix = resource, ''
        if resource.endswith('_edit'):
            base, suffix = resource[:-5], '/edit'
            if base not in EDIT_FORMS:
                raise ChatAIError('INVALID_ARGUMENTS')
        if resource.endswith('_new'):
            base = resource[:-4]
            if base not in FORM_NEW or identifier is not None:
                raise ChatAIError('INVALID_ARGUMENTS')
            path = '/dashboard/' + DETAILS[base] + '/new'
        elif base in DETAILS and type(identifier) is int and 0 < identifier <= 2147483647:
            path = '/dashboard/' + DETAILS[base] + '/' + str(identifier) + suffix
        elif resource in ROUTES and identifier is None:
            path = '/dashboard/' + ROUTES[resource]
        else:
            raise ChatAIError('INVALID_ARGUMENTS')
        if base not in ('user','users','store','stores'):
            path += '?store_id=' + str(company_id)
        return {'application':'gestion_magasin','resource':resource,'identifier':identifier,'company_id':company_id,'path':path}
