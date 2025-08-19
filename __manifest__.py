{
    'name': 'POS Paie Vendeur',
    'version': '15.0.2.0.0',
    'summary': 'Paie vendeurs basée sur les commandes BP existantes (sans modèles persistants)',
    'author': 'Votre Nom',
    'category': 'Point of Sale',
    'depends': ['base', 'pos_caisse'],
    'data': [
        'security/pos_paie_security.xml',
        'security/ir.model.access.csv',
        'views/pos_paie_views.xml',
        'views/pos_paie_menu.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
