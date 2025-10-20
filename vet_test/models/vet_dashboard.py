from odoo import fields, models, tools

class VetDashboard(models.Model):
    _name = "vet.dashboard"
    _description = "Vet Dashboard"
    _auto = False  # virtual model, no DB table created automatically

    name = fields.Char()
    value = fields.Integer()
    color = fields.Selection([
        ('primary', 'Blue'),
        ('success', 'Green'),
        ('warning', 'Yellow'),
        ('danger', 'Red')
    ])
    pending_count = fields.Integer()
    paid_count = fields.Integer()
    icon = fields.Char()
    url = fields.Char()

    def init(self):
        cr = self._cr
        table = self._table
        cr.execute(f"DROP VIEW IF EXISTS {table} CASCADE")
        cr.execute(f"""
            CREATE OR REPLACE VIEW {table} AS (
                SELECT
                    1 AS id,
                    'Animals' AS name,
                    (SELECT COUNT(*) FROM vet_animal) AS value,
                    'primary' AS color,
                    'fa fa-paw' AS icon,
                    '/odoo/action-948' AS url,
                    0 AS pending_count,
                    0 AS paid_count
                UNION ALL
                SELECT
                    2 AS id,
                    'Owners' AS name,
                    (SELECT COUNT(*) FROM vet_animal_owner) AS value,
                    'success' AS color,
                    'fa fa-user' AS icon,
                    '/odoo/action-824' AS url,
                    0 AS pending_count,
                    0 AS paid_count
                UNION ALL
                SELECT
                    3 AS id,
                    'Doctors' AS name,
                    (SELECT COUNT(*) FROM vet_animal_doctor) AS value,
                    'warning' AS color,
                    'fa fa-user-md' AS icon,
                    '/odoo/action-823' AS url,
                    0 AS pending_count,
                    0 AS paid_count
                UNION ALL
                SELECT
                    4 AS id,
                    'Invoices Overview' AS name,
                    0 AS value,
                    'graph' AS color,
                    'fa fa-money fa-2x text-success' AS icon,
                    '/web#action=vet_new.action_invoices_graph' AS url,
                    (SELECT COUNT(*) FROM account_move WHERE move_type='out_invoice' AND payment_state!='paid') AS pending_count,
                    (SELECT COUNT(*) FROM account_move WHERE move_type='out_invoice' AND payment_state='paid') AS paid_count
            )
        """)





