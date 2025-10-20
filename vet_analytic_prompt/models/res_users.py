from odoo import fields, models, api

class AccountAnalyticAccount(models.Model):
    _inherit = 'account.analytic.account'
    image = fields.Image(string="Image", max_width=128, max_height=128)

    def action_open_register(self):
        """POS-STYLE: LOCK USER + Open Visit form for THIS branch"""
        # LOCK USER TO THIS BRANCH
        self.env.user.write({'analytic_account_ids': [(6, 0, [self.id])]})
        
        # OPEN VISIT FORM WITH INVOICE FILTER
        return {
            'name': f'{self.name} Visit Register',
            'type': 'ir.actions.act_window',
            'res_model': 'vet.animal.visit',
            'view_mode': 'form',
            'view_id': False,
            'target': 'current',
            'context': {
                'default_analytic_account_id': self.id,
                'search_default_analytic_account_id': self.id  # Filter invoices by this branch
            },
        }
class ResUsers(models.Model):
    _inherit = 'res.users'
    analytic_account_ids = fields.Many2many(
        'account.analytic.account',
        string='Allowed Analytic Accounts',
        help='Analytic accounts this user can access for invoices.'
    )

class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    has_allowed_analytic = fields.Boolean(
        compute='_compute_has_allowed_analytic',
        search='_search_has_allowed_analytic'
    )

    def _compute_has_allowed_analytic(self):
        for line in self:
            user_accounts = self.env.user.analytic_account_ids
            line.has_allowed_analytic = any(
                f'"{acc.id}"' in (line.analytic_distribution or '') 
                for acc in user_accounts
            )

    def _search_has_allowed_analytic(self, operator, value):
        if operator == '=' and value:
            user_accounts = self.env.user.analytic_account_ids
            return [('analytic_distribution', 'ilike', f'"{acc.id}":') for acc in user_accounts]
        return []

class AccountMove(models.Model):
    _inherit = 'account.move'

    has_allowed_analytic = fields.Boolean(
        compute='_compute_has_allowed_analytic',
        search='_search_has_allowed_analytic'
    )

    analytic_display = fields.Char(
        compute='_compute_analytic_display',
        string="Analytic Distribution"
    )

    def _compute_has_allowed_analytic(self):
        for move in self:
            move.has_allowed_analytic = any(
                line.has_allowed_analytic for line in move.invoice_line_ids
            )

    def _search_has_allowed_analytic(self, operator, value):
        if operator == '=' and value:
            user_accounts = self.env.user.analytic_account_ids
            return [('id', 'in', self.env['account.move'].search([
                ('move_type', 'in', ('out_invoice', 'out_refund')),
                ('invoice_line_ids.analytic_distribution', 'ilike', f'"{acc.id}":')
            ]).ids) for acc in user_accounts]
        return []

    def _compute_analytic_display(self):
        for move in self:
            analytic_ids = set()
            for line in move.invoice_line_ids:
                if line.analytic_distribution:
                    for acc_id in line.analytic_distribution.keys():
                        analytic_ids.add(self.env['account.analytic.account'].browse(int(acc_id)).name)
            move.analytic_display = ', '.join(analytic_ids) if analytic_ids else False

    @api.model
    def create(self, vals):
        """Auto-set analytic if user locked, avoid duplicates"""
        if self.env.user.analytic_account_ids:
            analytic_id = self.env.user.analytic_account_ids[0].id
            # Check if invoice_line_ids exists and avoid duplicate creation
            invoice_lines = vals.get('invoice_line_ids', False)
            if not invoice_lines or not any(line for line in invoice_lines if isinstance(line, (list, tuple)) and len(line) > 2):
                # Add only one line with analytic if no valid lines exist
                vals.setdefault('invoice_line_ids', []).append((0, 0, {
                    'name': 'Treatment Charge',
                    'quantity': 1,
                    'price_unit': 700.00,
                    'analytic_distribution': {str(analytic_id): 100.0}
                }))
            else:
                # Update existing lines with analytic only for non-zero price
                for line in invoice_lines:
                    if isinstance(line, (list, tuple)) and len(line) > 2:
                        line_data = line[2]
                        if line_data.get('price_unit', 0) > 0:
                            line_data['analytic_distribution'] = {str(analytic_id): 100.0}
        return super(AccountMove, self).create(vals)
