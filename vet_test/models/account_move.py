from odoo import fields, models, api, _
from odoo.osv import expression
from datetime import datetime
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class AccountMove(models.Model):
    _inherit = 'account.move'

    # ✅ NEW FIELD (KEEP AT TOP)
    analytic_account_id = fields.Many2one(
        'account.analytic.account',
        string="Primary Branch",
        compute='_compute_analytic_account_id',
        store=True,
        index=True
    )

    # ===================== BASIC FIELDS =====================
    visit_id = fields.Many2one('vet.animal.visit', string="Animal Visit")
    animal_display_name = fields.Char(
        string="Animal Display Name",
        compute="_compute_animal_display_name",
        store=True
    )
    amount_paid = fields.Monetary(
        string="Amount Paid",
        compute="_compute_amount_paid",
        currency_field="currency_id",
        store=True
    )

    # Extract / digitization (placeholders)
    extract_error_message = fields.Char(string="Extract Error Message")
    extract_document_uuid = fields.Char()
    extract_state = fields.Char()
    extract_attachment_id = fields.Many2one('ir.attachment')
    extract_can_show_send_button = fields.Boolean()
    extract_can_show_banners = fields.Boolean()

    # ===================== DASHBOARD TOTALS =====================
    dashboard_total_all = fields.Monetary(
        compute="_compute_dashboard_non_stored",
        currency_field="currency_id",
        string="Total Invoiced",
        store=False,
        compute_sudo=False
    )
    dashboard_total_cash = fields.Monetary(
        compute="_compute_dashboard_stored",
        currency_field="currency_id",
        string="Cash Payments",
        store=True,
        compute_sudo=True
    )
    dashboard_total_bank = fields.Monetary(
        compute="_compute_dashboard_stored",
        currency_field="currency_id",
        string="Bank Payments",
        store=True,
        compute_sudo=True
    )
    dashboard_total_online = fields.Monetary(
        compute="_compute_dashboard_stored",
        currency_field="currency_id",
        string="Online/Credit Payments",
        store=True,
        compute_sudo=True
    )
    dashboard_total_discount = fields.Monetary(
        compute="_compute_dashboard_non_stored",
        currency_field="currency_id",
        string="Discount (on Cash)",
        store=False,
        compute_sudo=False
    )

    payment_method = fields.Selection(
        related="visit_id.payment_method",
        store=True,
        readonly=False,
        string="Payment Method"
    )

    # ===================== ANALYTIC FIELDS =====================
    has_allowed_analytic = fields.Boolean(
        compute='_compute_has_allowed_analytic',
        search='_search_has_allowed_analytic'
    )
    analytic_display = fields.Char(
        compute='_compute_analytic_display',
        string="Analytic Distribution",
        store=True
    )

    # ===================== COMPUTE METHODS =====================
    @api.depends("visit_id", "visit_id.animal_id", "visit_id.animal_id.name")
    def _compute_animal_display_name(self):
        for move in self:
            move.animal_display_name = move.visit_id.animal_id.name if move.visit_id and move.visit_id.animal_id else ""

    @api.depends("amount_total", "amount_residual")
    def _compute_amount_paid(self):
        for move in self:
            move.amount_paid = move.amount_total - move.amount_residual

    @api.depends('amount_total', 'payment_method')
    def _compute_dashboard_stored(self):
        for rec in self:
            rec.dashboard_total_cash = rec.amount_total if (rec.payment_method or '').lower() == 'cash' else 0.0
            rec.dashboard_total_bank = rec.amount_total if (rec.payment_method or '').lower() == 'bank' else 0.0
            rec.dashboard_total_online = rec.amount_total if (rec.payment_method or '').lower() in ('online', 'credit', 'credit_card') else 0.0
            _logger.debug(
                "Computed stored totals for move %s: cash=%s, bank=%s, online=%s",
                rec.name, rec.dashboard_total_cash, rec.dashboard_total_bank, rec.dashboard_total_online
            )

    @api.depends('amount_total', 'invoice_line_ids.discount', 'invoice_line_ids.price_unit', 'invoice_line_ids.quantity', 'payment_method')
    def _compute_dashboard_non_stored(self):
        for rec in self:
            total_discount = 0.0
            if (rec.payment_method or '').lower() == 'cash':
                for line in rec.invoice_line_ids:
                    total_discount += (line.price_unit * line.quantity) * (line.discount / 100.0)
            rec.dashboard_total_all = rec.amount_total
            rec.dashboard_total_discount = total_discount
            _logger.debug(
                "Computed non-stored totals for move %s: all=%s, discount=%s",
                rec.name, rec.dashboard_total_all, rec.dashboard_total_discount
            )

    # ✅ NEW METHOD - ADD THIS!
    @api.depends('invoice_line_ids.analytic_distribution')
    def _compute_analytic_account_id(self):
        for move in self:
            primary_id = False
            for line in move.invoice_line_ids:
                if line.analytic_distribution:
                    first_key = next(iter(line.analytic_distribution.keys()), None)
                    if first_key:
                        primary_id = int(first_key)
                        break
            move.analytic_account_id = self.env['account.analytic.account'].browse(primary_id) if primary_id else False

    @api.model_create_multi
    def create(self, vals_list):
        if not isinstance(vals_list, list):
            vals_list = [vals_list]
        try:
            default_account = self.env['ir.property'].sudo().get('property_account_income_categ_id', 'product.category')
            if not default_account:
                _logger.warning("No default income account found via ir.property, searching for fallback.")
                default_account = self.env['account.account'].sudo().search([('account_type', '=', 'income')], limit=1)
        except KeyError:
            _logger.error("ir.property model not found, falling back to first income account.")
            default_account = self.env['account.account'].sudo().search([('account_type', '=', 'income')], limit=1)
        moves = super(AccountMove, self).create(vals_list)
        for move in moves:
            analytic_id = self.env.user.analytic_account_ids and self.env.user.analytic_account_ids[0].id
            if analytic_id and not move.invoice_line_ids:
                move.write({'invoice_line_ids': [(0, 0, {
                    'name': 'Treatment Charge',
                    'quantity': 1,
                    'price_unit': 700.00,
                    'account_id': default_account.id if default_account else False,
                    'analytic_distribution': {str(analytic_id): 100.0}
                })]})
            elif analytic_id:
                for line in move.invoice_line_ids:
                    if not line.analytic_distribution and line.account_id and line.account_id.account_type in ('income', 'expense'):
                        line.analytic_distribution = {str(analytic_id): 100.0}
                        line._compute_analytic_distribution()
            move._compute_analytic_display()
        return moves

    def action_post(self):
        return super().action_post()

    # ✅ FIXED read_group
    @api.model
    def read_group(self, domain, fields, groupby, offset=0, limit=None, orderby=False, lazy=True):
        # FILTER BY USER'S BRANCHES
        user_branches = self.env.user.analytic_account_ids
        if user_branches:
            branch_domain = [('analytic_account_id', 'in', user_branches.ids)]
            domain = expression.AND([domain or [], branch_domain])
        
        res = super().read_group(domain, fields, groupby, offset=offset, limit=limit, orderby=orderby, lazy=lazy)
        all_records = self.search(domain)
        totals = self._compute_global_totals(all_records)

        for group in res:
            if not group.get('__domain'):
                continue
            group_records = self.search(group['__domain'])
            group_totals = self._compute_global_totals(group_records)
            group.update({
                'dashboard_total_cash': group_totals['dashboard_total_cash'],
                'dashboard_total_bank': group_totals['dashboard_total_bank'],
                'dashboard_total_online': group_totals['dashboard_total_online'],
                'amount_total': sum(group_records.mapped('amount_total')) or 0.0,
                '__count': len(group_records),
            })
        return res

    def _compute_global_totals(self, records):
        total_cash = sum(rec.amount_total for rec in records if (rec.payment_method or '').lower() == 'cash')
        total_bank = sum(rec.amount_total for rec in records if (rec.payment_method or '').lower() == 'bank')
        total_online = sum(rec.amount_total for rec in records if (rec.payment_method or '').lower() in ('online', 'credit', 'credit_card'))
        return {
            'dashboard_total_cash': total_cash,
            'dashboard_total_bank': total_bank,
            'dashboard_total_online': total_online,
        }

    def action_print_visit_receipt_from_invoice(self):
        self.ensure_one()
        invoices = self if len(self) == 1 else self
        visits = invoices.mapped('visit_id').filtered(lambda v: v.exists())

        if not visits:
            origins = list(set(invoices.mapped('invoice_origin')))
            if origins:
                visits = self.env['vet.animal.visit'].search([('name', 'in', origins)])
            if not visits:
                raise UserError(_("No related visit found for this invoice."))

        return self.env.ref('vet_test.action_report_visit_receipt').report_action(visits)

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

    # ✅ FIXED - REMOVE THE CACHE LINE
    @api.depends('invoice_line_ids.analytic_distribution')
    def _compute_analytic_display(self):
        for move in self:
            analytic_ids = set()
            for line in move.invoice_line_ids:
                if line.analytic_distribution:
                    for acc_id in line.analytic_distribution.keys():
                        analytic_account = self.env['account.analytic.account'].browse(int(acc_id))
                        if analytic_account.exists() and analytic_account.name:
                            analytic_ids.add(analytic_account.name)
            move.analytic_display = ', '.join(sorted(analytic_ids)) if analytic_ids else False

# ===================== ACCOUNT PAYMENT RECONCILIATION =====================
class AccountPayment(models.Model):
    _inherit = 'account.payment'

    def action_post(self):
        res = super().action_post()
        for payment in self:
            invoices = payment.invoice_ids
            if invoices and payment.move_id:
                lines_to_reconcile = payment.move_id.line_ids | invoices.mapped('line_ids')
                if lines_to_reconcile:
                    try:
                        lines_to_reconcile.reconcile()
                    except Exception as e:
                        _logger.warning("Reconciliation failed: %s", e)
        return res

class AccountAnalyticAccount(models.Model):
    _inherit = 'account.analytic.account'
    image = fields.Image(string="Image", max_width=128, max_height=128)
    
    # ✅ FIXED - NOW OPENS INVOICES FOR THIS BRANCH
    def action_open_register(self):
        """🚨 GULSHAN LOCK + FILTER - NO CHOICE NEEDED!"""
        self.ensure_one()
        
        # ✅ STEP 1: LOCK USER TO THIS BRANCH ONLY
        self.env.user.write({'analytic_account_ids': [(6, 0, [self.id])]})
        
        # ✅ STEP 2: GET GULSHAN DOCTORS ONLY
        gulshan_doctors = self.env['hr.employee'].search([
            ('analytic_account_id', '=', self.id),  # Doctors assigned to this branch
            ('job_id.name', 'ilike', 'doctor')      # Only doctors
        ])
        
        # ✅ STEP 3: FILTER VISITS - GULSHAN ONLY
        gulshan_visits = self.env['vet.animal.visit'].search([
            ('analytic_account_id', '=', self.id),  # GULSHAN BRANCH ONLY
            ('state', 'in', ['draft', 'confirmed']), # Open visits only
        ], order='create_date desc', limit=20)
        
        # ✅ STEP 4: OPEN GULSHAN VISIT FORM WITH FILTERS
        return {
            'name': f'🏥 {self.name} Visit Register',
            'type': 'ir.actions.act_window',
            'res_model': 'vet.animal.visit',
            'view_mode': 'list,form',
            'views': [(False, 'list'), (False, 'form')],
            'target': 'current',
            'domain': [                       # ✅ GULSHAN FILTER
                ('analytic_account_id', '=', self.id),
                '|', ('state', '=', 'draft'), ('state', '=', 'confirmed')
            ],
            'context': {
                'default_analytic_account_id': self.id,           # Default = GULSHAN
                'default_employee_id': (gulshan_doctors[0].id if gulshan_doctors else False), # Default GULSHAN DOCTOR
                'search_default_analytic_account_id': self.id,    # Filter list = GULSHAN ONLY
                'search_default_my_visits': 1,                    # Show only my visits
                'default_group_by': 'employee_id',                # Group by GULSHAN DOCTORS
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
