"""Permission-filtered EN/FR commands; described searches and useful bare-command help."""
import re
from chat_ai_assistant.clarifications import message_language
from chat_ai_assistant.routing import normalized
from chat_ai_assistant.contracts import ChatAIError
from .security import capabilities
from .labels import RESOURCE_LABELS
MODULES=[('/articles','product'),('/stock','stock'),('/ventes','sale'),('/clients','customer'),('/depenses','expense'),('/achats','purchase'),('/transferts','transfer'),('/inventaires','inventory'),('/promotions','promotion'),('/pointage','attendance'),('/employes','employee'),('/demandes','stock_request'),('/magasins','store'),('/utilisateurs','user')]
ALIASES={'/products':'/articles','/sales':'/ventes','/customers':'/clients','/expenses':'/depenses','/purchases':'/achats','/transfers':'/transferts','/inventories':'/inventaires','/attendance':'/pointage','/employees':'/employes','/requests':'/demandes','/stores':'/magasins','/users':'/utilisateurs','/search':'/voir','/chercher':'/voir','/edit':'/modifier','/delete':'/supprimer','/help':'/aide','/summary':'/bilan'}

def shortcut_catalog(user,store_id,language='fr'):
    en=language=='en';caps=capabilities(user,store_id);items=[]
    for command,resource in MODULES:
        if 'read_'+resource not in caps:continue
        example=command+' '+('Demo Example' if en else 'Démo Exemple')
        if resource=='stock':example='/stock '+('products with low stock' if en else 'articles en stock faible')
        if resource=='sale':example='/ventes '+('customer Démo Atlas and product Démo Café' if en else 'client Démo Atlas et article Démo Café')
        items.append({'command':command,'title':RESOURCE_LABELS[resource][int(en)],'help':'Describe the name, product or record you want to find in the active store.' if en else 'Décrivez le nom, l’article ou le document à retrouver dans le magasin actif.','example':example})
    additions=[('/aide','Aide des raccourcis','Shortcut help','read')]
    if items:additions.insert(0,('/voir','Rechercher un document','Find a record','read'))
    if any('read_'+r in caps for r in ('product','customer','expense','attendance','sale')) and {'store_management','store_write'}&caps:
        additions.extend([('/modifier','Modifier après confirmation','Edit with confirmation','update'),('/supprimer','Supprimer après confirmation','Delete with confirmation','delete')])
    if 'read_sale' in caps:additions.append(('/pdf','Facture de vente en gros','Wholesale invoice PDF','print'))
    if 'financial' in caps:additions.append(('/bilan','Indicateurs du magasin','Store dashboard figures','financial'))
    for command,fr,english,cap in additions:
        if cap not in caps:continue
        help_text=('State the exact metric and dates. Sales, paid amounts and accounting profit differ.' if en else 'Précisez l’indicateur et les dates. Ventes, montants payés et bénéfice comptable sont différents.') if command=='/bilan' else ('Describe the record; select the matching result before a change.' if en else 'Décrivez le document ; choisissez le bon résultat avant une modification.')
        if command=='/aide':help_text='Show the commands available with your permissions.' if en else 'Afficher les commandes disponibles selon vos autorisations.'
        items.append({'command':command,'title':english if en else fr,'help':help_text,'example':command if command=='/aide' else command+' '+('expense Demo Supplies' if en else 'dépense Démo Fournitures')})
    return items

def suggestions(user,store_id,language='fr'):
    en=language=='en';caps=capabilities(user,store_id);items=[]
    for cap,fr,english in [('read_product','Retrouve un article par désignation ou code barre.','Find a product by name or barcode.'),('read_stock','Montre les articles en stock faible.','Show products with low stock.'),('read_sale','Affiche les dernières ventes du magasin.','Show the store’s latest sales.'),('read_expense','Affiche les dernières dépenses.','Show the latest expenses.'),('read_attendance','Montre les derniers pointages.','Show the latest attendance records.')]:
        if cap in caps:items.append(english if en else fr)
    if not items:items=['How do I use the checkout?' if en else 'Comment utiliser la caisse ?']
    return items[:5]

def shortcut_action(text,executor=None,interface_language='fr'):
    if not text.startswith('/'):return None
    parts=text.split(maxsplit=1);command=ALIASES.get(parts[0].casefold(),parts[0].casefold());arg=parts[1].strip() if len(parts)>1 else ''
    if command=='/' and not arg:command='/aide'
    language=message_language(text,interface_language);en=language=='en'
    catalog=shortcut_catalog(executor.authorize(),executor.company_id,language);item=next((x for x in catalog if x['command']==command),None)
    if not item:
        if command in dict(MODULES) or command in ('/modifier','/supprimer','/pdf','/bilan','/voir'):raise ChatAIError('PERMISSION_DENIED')
        return {'tool':'clarify','message':'Unknown command. Send /help.' if en else 'Commande inconnue. Envoyez /aide.'}
    if command=='/aide':return {'tool':'clarify','message':'\n'.join(x['command']+' : '+x['title'] for x in catalog)}
    resource=dict(MODULES).get(command)
    if resource and not arg:return {'tool':'search_records','arguments':{'resource':resource},'usage_message':item['help']+' '+item['example']}
    if not arg:return {'tool':'clarify','message':item['help']+' '+item['example']}
    return None

def reference_action(text,state):
    if not state.get('ids'):return None
    words=normalized(text).strip().rstrip('.!?')
    values={'first':1,'second':2,'third':3,'premier':1,'premiere':1,'deuxieme':2,'troisieme':3}
    match=re.fullmatch(r'(?:open (?:the )?|ouvre (?:le |la )?)(first|second|third|premier|premiere|deuxieme|troisieme)(?: one| result| resultat)?',words)
    return {'tool':'previous_results','arguments':{'operation':'open','index':values[match[1]]}} if match else None

def knowledge_action(text):
    words=normalized(text).strip()
    if len(text)<300 and not re.search(r'\d|\b(?:then|puis|ensuite|ignore|et|and|current|this|ce|cette)\b',words) and re.match(r'^(?:how (?:do i|to)|comment (?:creer|retrouver|trouver|modifier|supprimer|utiliser)|que signifie|what does)\b',words):return {'tool':'knowledge','arguments':{'query':text}}
    return None

def greeting_action(text):
    words=re.sub(r'\s+',' ',normalized(text).strip().rstrip('.!?').strip())
    if words in {'hello','hi','hey','good morning','good afternoon','good evening','hello there'}:return {'tool':'clarify','message':'Hello! How can I help you in Gestion Magasin?'}
    if words in {'bonjour','salut','bonsoir','coucou','bonjour a tous'}:return {'tool':'clarify','message':'Bonjour ! Comment puis-je vous aider dans Gestion Magasin ?'}
    if words in {'thanks','thank you','thank you very much'}:return {'tool':'clarify','message':'You’re welcome!'}
    if words in {'merci','merci beaucoup'}:return {'tool':'clarify','message':'Avec plaisir !'}
    return None
