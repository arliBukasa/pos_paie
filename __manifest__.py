{
    'name': 'POS Paie Vendeur',
    'version': '15.0.2.1.0',
    'summary': 'Paie vendeurs basée sur les commandes BP existantes (sans modèles persistants)',
    'author': 'Votre Nom',
    'category': 'Point of Sale',
    'depends': ['base', 'pos_caisse'],
    "data": [
        "security/ir.model.access.csv",
        "security/pos_paie_security.xml",
        "views/pos_paie_menu.xml",
        "views/pos_paie_views.xml",
        "reports/pos_paie_periode_ligne_report.xml",
        "reports/pos_paie_periode_report.xml"
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
