{
    'name': 'Analytic Dashboard',
    'version': '1.0',
    'summary': 'Dashboard for Analytic Accounts with POS-like Display and Invoice Restrictions',
    'description': """
        - Adds a Kanban dashboard for analytic accounts similar to POS.
        - Shows all analytic accounts.
        - Restricts invoice visibility based on user's assigned analytic accounts.
    """,
    'author': 'Grok Assisted Development',
    'depends': ['account', 'point_of_sale'],
    'data': [
        'security/analytic_security.xml',
        'views/analytic_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'vet_analytic_prompt/static/src/css/analytic.css',  # CSS ONLY
        ],
    },
    'sequence':-999,
    'installable': True,
    'application': False,
    'auto_install': False,
}
