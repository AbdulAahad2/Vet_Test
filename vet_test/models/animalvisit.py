from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
import logging
import uuid

_logger = logging.getLogger(__name__)

class VetAnimalVisit(models.Model):
    _name = "vet.animal.visit"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Animal Visit"
    _order = "date desc"
    _rec_name = "name"

    name = fields.Char(string="Visit Reference", readonly=True, copy=False, default=lambda self: _("New"))
    date = fields.Datetime(default=fields.Datetime.now)
    animal_id = fields.Many2one("vet.animal", string="Animal", required=True)
    selected_animal_id = fields.Many2one('vet.animal', string="Select Animal")
    animal_ids = fields.Many2many('vet.animal', compute='_compute_animals_for_owner', string="Owner's Animals")
    animal_name = fields.Many2one('vet.animal', string="Animal Name")
    animal_display_name = fields.Char(string="Animal Name", compute="_compute_animal_display_name", store=True)
    animal_pic = fields.Image(string="Animal Picture", related='animal_id.image_1920', store=True, readonly=False)
    debug_animal_pic = fields.Char(compute="_compute_debug_animal_pic")
    owner_id = fields.Many2one('vet.animal.owner', string="Owner")
    contact_number = fields.Char(string="Owner Contact")
    doctor_id = fields.Many2one("vet.animal.doctor", string="Doctor")
    notes = fields.Text("Notes")
    treatment_charge = fields.Float(default=0.0)
    discount_percent = fields.Float(string="Discount (%)", default=0.0)
    discount_fixed = fields.Float(string="Discount (Fixed)", default=0.0)
    subtotal = fields.Float(compute="_compute_totals", store=True)
    total_amount = fields.Float(compute='_compute_totals', store=True)

    payment_method = fields.Selection(
        [('cash', 'Cash'), ('bank', 'Bank')],
        string="Payment Method",
        default='cash'
    )

    is_fully_paid = fields.Boolean(
        string="Fully Paid",
        compute="_compute_is_fully_paid",
        store=False
    )

    line_ids = fields.One2many('vet.animal.visit.line', 'visit_id', string="Visit Lines")
    medicine_line_ids = fields.One2many(
        'vet.animal.visit.line', 'visit_id',
        domain=[('service_id.service_type', '=', 'vaccine')],
        string="Medicine Lines"
    )
    service_line_ids = fields.One2many(
        'vet.animal.visit.line', 'visit_id',
        domain=[('service_id.service_type', '=', 'service')],
        string="Service Lines"
    )
    test_line_ids = fields.One2many(
        'vet.animal.visit.line', 'visit_id',
        domain=[('service_id.service_type', '=', 'test')],
        string="Test Lines"
    )
    receipt_lines = fields.One2many(
        'vet.animal.visit.line', 'visit_id',
        compute='_compute_receipt_lines',
        string="Receipt Lines"
    )

    invoice_ids = fields.One2many('account.move', 'visit_id', string="Invoices")
    payment_state = fields.Selection(
        [('not_paid', 'Not Paid'), ('partial', 'Partially Paid'), ('paid', 'Paid')],
        string="Payment Status", compute="_compute_payment_state", store=True
    )
    has_unpaid_invoice = fields.Boolean(
        string="Has Unpaid Invoice",
        compute="_compute_has_unpaid_invoice",
        store=True
    )
    state = fields.Selection(
        [('draft', 'Draft'), ('confirmed', 'Confirmed'), ('done', 'Done'), ('cancel', 'Cancelled')],
        default='draft'
    )
    delivered = fields.Boolean(default=False, string="Products Delivered")
    amount_received = fields.Float(compute='_compute_amount_received')
    latest_payment_amount = fields.Float(
        string="Latest Payment Amount",
        default=0.0,
        help="Amount of the most recent payment made for this visit."
    )

    owner_unpaid_balance = fields.Float(
        string="Unpaid Balance",
        compute="_compute_owner_unpaid_balance",
        store=False,
        digits=(16, 2),
    )

    @api.depends('latest_payment_amount', 'invoice_ids', 'invoice_ids.state', 'invoice_ids.amount_residual')
    def _compute_amount_received(self):
        for visit in self:
            visit.amount_received = visit.latest_payment_amount or 0.0

    @api.depends('owner_id.partner_id')
    def _compute_has_unpaid_invoice(self):
        AccountMove = self.env['account.move']
        for visit in self:
            has_unpaid = False
            partner = visit.owner_id.partner_id
            if partner:
                unpaid = AccountMove.search_count([
                    ('partner_id', '=', partner.id),
                    ('move_type', '=', 'out_invoice'),
                    ('payment_state', 'in', ['not_paid', 'partial']),
                ])
                has_unpaid = unpaid > 0
            visit.has_unpaid_invoice = has_unpaid

    @api.depends('payment_state')
    def _compute_is_fully_paid(self):
        for visit in self:
            visit.is_fully_paid = visit.payment_state == 'paid'

    @api.depends('animal_id', 'animal_id.image_1920')
    def _compute_debug_animal_pic(self):
        for rec in self:
            if rec.animal_id:
                _logger.info(
                    "VetAnimalVisit[%s]: animal_id=%s, image_1920 exists=%s, animal_pic exists=%s",
                    rec.id,
                    rec.animal_id.name,
                    bool(rec.animal_id.image_1920),
                    bool(rec.animal_pic)
                )
                rec.debug_animal_pic = str(bool(rec.animal_pic))
            else:
                _logger.warning("VetAnimalVisit[%s]: No animal_id set", rec.id)
                rec.debug_animal_pic = "No animal_id"

    @api.depends('animal_id.image_1920')
    def _compute_animal_pic(self):
        for rec in self:
            rec.animal_pic = rec.animal_id.image_1920 or False

    @api.depends("animal_id")
    def _compute_animal_display_name(self):
        for record in self:
            record.animal_display_name = record.animal_id.name if record.animal_id else ""

    @api.depends('owner_id', 'contact_number')
    def _compute_animals_for_owner(self):
        for record in self:
            if record.owner_id:
                animals = self.env['vet.animal'].search([('owner_id', '=', record.owner_id.id)])
            elif record.contact_number:
                partners = self.env['res.partner'].search([('phone', '=', record.contact_number)])
                animals = self.env['vet.animal'].search([('owner_id', 'in', partners.ids)]) if partners else self.env['vet.animal'].browse()
            else:
                animals = self.env['vet.animal'].browse()
            record.animal_ids = animals

    @api.depends(
        'service_line_ids.quantity', 'service_line_ids.price_unit',
        'test_line_ids.quantity', 'test_line_ids.price_unit',
        'medicine_line_ids.quantity', 'medicine_line_ids.price_unit',
        'treatment_charge', 'discount_percent', 'discount_fixed'
    )
    def _compute_totals(self):
        for visit in self:
            all_lines = visit.service_line_ids + visit.test_line_ids + visit.medicine_line_ids
            subtotal = sum(line.quantity * line.price_unit for line in all_lines if line.quantity and line.price_unit)
            visit.subtotal = subtotal
            total = subtotal + (visit.treatment_charge or 0.0)
            if visit.discount_percent > 0:
                total -= total * (visit.discount_percent / 100.0)
            elif visit.discount_fixed > 0:
                total -= visit.discount_fixed
            visit.total_amount = float(total or 0.0)
            _logger.info("Visit %s: Computed totals fixed - subtotal=%s, total_amount=%s", visit.name, visit.subtotal, visit.total_amount)

    @api.depends('service_line_ids.quantity', 'service_line_ids.price_unit', 'test_line_ids.quantity', 'test_line_ids.price_unit', 'medicine_line_ids.quantity', 'medicine_line_ids.price_unit')
    def _compute_receipt_lines(self):
        for visit in self:
            all_lines = visit.service_line_ids + visit.test_line_ids + visit.medicine_line_ids
            visit.receipt_lines = all_lines.filtered(lambda l: l.quantity > 0 and l.product_id and l.price_unit > 0)
            if not visit.receipt_lines:
                _logger.warning("Visit %s: No valid receipt lines (filtered quantity>0, product_id, price_unit>0)", visit.name)
            else:
                _logger.debug("Visit %s: Receipt lines computed - count=%s", visit.name, len(visit.receipt_lines))

    @api.depends('invoice_ids.payment_state')
    def _compute_payment_state(self):
        for visit in self:
            if not visit.invoice_ids:
                visit.payment_state = 'not_paid'
            else:
                total_amount = sum(visit.invoice_ids.mapped('amount_total'))
                residual_amount = sum(visit.invoice_ids.mapped('amount_residual'))
                if residual_amount == 0 and total_amount > 0:
                    visit.payment_state = 'paid'
                elif residual_amount < total_amount and residual_amount > 0:
                    visit.payment_state = 'partial'
                else:
                    visit.payment_state = 'not_paid'

            old_state = visit.state
            new_state = visit.state

            if old_state == 'cancel':
                continue

            if visit.payment_state == 'paid':
                new_state = 'done'
            elif visit.invoice_ids:
                new_state = 'confirmed'
            else:
                new_state = 'draft'

            if new_state != old_state:
                visit.with_context(skip_visit_validation=True).write({'state': new_state})
                _logger.info("Visit %s: State sync: %s -> %s (payment_state=%s)",
                             visit.name, old_state, new_state, visit.payment_state)

    @api.depends("owner_id")
    def _compute_owner_unpaid_balance(self):
        for visit in self:
            visit.owner_unpaid_balance = visit._get_owner_unpaid_balance()

    def action_confirm(self):
        for visit in self:
            if visit.state == 'draft':
                visit.with_context(skip_visit_validation=True).write({'state': 'confirmed'})
                _logger.info("Visit %s: Confirmed, state set to 'confirmed'", visit.name)
                visit.message_post(body=_("Visit confirmed."))

    def action_cancel(self):
        for visit in self:
            if visit.state in ['draft', 'confirmed']:
                if visit.invoice_ids.filtered(lambda inv: inv.state == 'posted'):
                    raise UserError(_("Cannot cancel a visit with posted invoices. Please cancel the invoices first."))
                visit.with_context(skip_visit_validation=True).write({'state': 'cancel'})
                _logger.info("Visit %s: Cancelled, state set to 'cancel'", visit.name)
                visit.message_post(body=_("Visit cancelled."))

    @api.model
    def create(self, vals):
        if vals.get("name", _("New")) == _("New"):
            vals["name"] = self.env["ir.sequence"].next_by_code("vet.animal.visit") or "VIS00000"
        return super().create(vals)

    def write(self, vals):
        if self.env.context.get('skip_visit_validation') or self.env.context.get('from_payment_wizard'):
            return super().write(vals)

        if set(vals.keys()).issubset(['is_fully_paid', 'notes', 'latest_payment_amount']):
            return super().write(vals)

        for visit in self:
            if visit.state in ['confirmed', 'done']:
                allowed_fields = ['notes', 'latest_payment_amount']
                restricted_fields = [key for key in vals.keys() if key not in allowed_fields]
                final_restricted_fields = []
                for key in restricted_fields:
                    field = visit._fields.get(key)
                    if field and field.compute and not field.store:
                        continue
                    final_restricted_fields.append(key)

                if 'state' in final_restricted_fields:
                    new_state = vals.get('state')
                    if visit.state == 'confirmed' and new_state in ['done', 'cancel']:
                        if new_state == 'done' and visit.payment_state != 'paid':
                            raise UserError(
                                _("Cannot set visit %s to 'done' unless payment state is 'paid'.") % visit.name
                            )
                        if new_state == 'cancel' and visit.invoice_ids.filtered(lambda inv: inv.state == 'posted'):
                            raise UserError(
                                _("Cannot cancel visit %s with posted invoices. Please cancel the invoices first.") % visit.name
                            )
                        final_restricted_fields.remove('state')
                    else:
                        raise UserError(
                            _("Invalid state transition for visit %s from %s to %s.") % (
                                visit.name, visit.state, new_state
                            )
                        )

                receipt_related_fields = [
                    'line_ids', 'service_line_ids', 'test_line_ids', 'medicine_line_ids',
                    'treatment_charge', 'discount_percent', 'discount_fixed'
                ]

                receipt_fields_attempted = [key for key in final_restricted_fields if key in receipt_related_fields]
                other_restricted_fields = [key for key in final_restricted_fields if key not in receipt_related_fields]

                if receipt_fields_attempted:
                    raise UserError(
                        _("Cannot modify receipt-related fields for visit %s in %s state. "
                          "Receipt fields attempted: %s. Only %s can be updated.") % (
                              visit.name, visit.state, ', '.join(receipt_fields_attempted),
                              ', '.join(allowed_fields) or 'no fields'
                          )
                    )
                if other_restricted_fields:
                    raise UserError(
                        _("Cannot modify visit %s in %s state. "
                          "Non-receipt fields attempted: %s. Only %s can be updated.") % (
                              visit.name, visit.state, ', '.join(other_restricted_fields),
                              ', '.join(allowed_fields) or 'no fields'
                          )
                    )
        return super().write(vals)

    def print_visit_receipt(self):
        return self.env.ref('vet_test.action_report_visit_receipt').report_action(self)

    @api.onchange('owner_id')
    def _onchange_owner_id(self):
        domain = {'animal_id': []}
        if self.owner_id:
            self.contact_number = self.owner_id.contact_number or ''
            animals = self.env['vet.animal'].search([('owner_id', '=', self.owner_id.id)])
            if len(animals) == 1:
                self.animal_id = animals[0]
            domain = {'animal_id': [('owner_id', '=', self.owner_id.id)]}
        else:
            self.contact_number = ''
            self.animal_id = False
            domain = {'animal_id': [('id', '!=', False)]}
        return {'domain': domain}

    @api.onchange('contact_number')
    def _onchange_contact_number(self):
        self.owner_id = False
        self.animal_id = False
        if self.contact_number:
            owner = self.env['vet.animal.owner'].search([('contact_number', '=', self.contact_number.strip())], limit=1)
            if owner:
                self.owner_id = owner
                animals = self.env['vet.animal'].search([('owner_id', '=', owner.id)])
                if len(animals) == 1:
                    self.animal_id = animals[0]
                domain = {'animal_id': [('owner_id', '=', owner.id)]}
            else:
                domain = {'animal_id': [('id', '!=', False)]}
        else:
            domain = {'animal_id': [('id', '!=', False)]}
        return {'domain': domain, 'value': {'owner_id': self.owner_id, 'animal_id': self.animal_id}}

    @api.onchange('animal_id')
    def _onchange_animal_id(self):
        if not self.animal_id:
            self.owner_id = False
            self.contact_number = ''
            self.animal_ids = False
            self.selected_animal_id = False
            self.animal_name = False
            return
        self.owner_id = self.animal_id.owner_id
        self.contact_number = self.owner_id.contact_number or ''
        self.animal_ids = self.env['vet.animal'].search([('owner_id', '=', self.owner_id.id)])
        self.selected_animal_id = self.animal_id
        self.animal_name = self.animal_id

    def action_print_visit_receipt(self):
        self.ensure_one()
        if not self.exists():
            raise UserError(_("This visit record no longer exists."))
        _logger.info("Printing visit receipt - visit id=%s name=%s for user=%s", self.id, self.name, self.env.uid)
        return self.env.ref("vet_test.action_report_visit_receipt").report_action(self)

    @api.model
    def print_visit_receipt(self, docids):
        valid_visits = self.env['vet.animal.visit'].browse(docids).filtered(lambda r: r.exists())
        if not valid_visits:
            raise UserError(_("No valid visit records found to print."))
        return self.env.ref('vet_test.action_report_visit_receipt').report_action(valid_visits)

    def action_print_receipt(self):
        self.ensure_one()
        return self.env.ref("vet_test.action_report_visit_receipt").report_action(self)

    def _sync_state_with_payment(self):
        for visit in self:
            if visit.state == "cancel":
                continue
            new_state = 'draft'
            if visit.payment_state == "paid":
                new_state = "done"
            elif visit.invoice_ids:
                new_state = "confirmed"
            else:
                new_state = 'draft'

            if new_state != visit.state:
                visit.with_context(skip_visit_validation=True).write({'state': new_state})
                _logger.info("Visit %s: State synced to %s (payment_state=%s)",
                             visit.name, new_state, visit.payment_state)

    @api.constrains('payment_state', 'state')
    def _constrain_payment_state(self):
        for visit in self:
            if visit.state not in ['draft', 'cancel']:
                expected_state = 'done' if visit.payment_state == 'paid' else 'confirmed'
                if visit.state != expected_state:
                    visit.with_context(skip_visit_validation=True).write({'state': expected_state})
                    _logger.info("Visit %s: Constrained state to %s due to payment_state=%s",
                                 visit.name, expected_state, visit.payment_state)

    def _get_owner_unpaid_balance(self, exclude_visits=None):
        self.ensure_one()
        if not self.owner_id or not self.owner_id.partner_id:
            _logger.info("Visit %s: No owner_id or partner_id found, returning 0.0", self.name)
            return 0.0

        self.env["account.move"].invalidate_model(["amount_residual", "payment_state"])

        domain = [
            ("partner_id", "=", self.owner_id.partner_id.id),
            ("move_type", "=", "out_invoice"),
            ("state", "=", "posted"),
            ("payment_state", "in", ["not_paid", "partial"]),
        ]

        if exclude_visits:
            domain.append(("visit_id", "not in", exclude_visits))

        invoices = self.env["account.move"].search(domain)
        balance = sum(invoices.mapped('amount_residual'))
        _logger.info("Visit %s: Calculated unpaid balance: %s for invoices %s",
                     self.name, balance, invoices.mapped('name'))
        return balance

    def _get_or_create_partner_from_owner(self, owner):
        if owner.partner_id:
            return owner.partner_id
        partner = self.env['res.partner'].create({
            'name': owner.name,
            'phone': owner.contact_number,
            'email': owner.email,
        })
        owner.partner_id = partner.id
        return partner

    @api.constrains('discount_percent', 'discount_fixed')
    def _check_discount_conflict(self):
        for visit in self:
            if visit.discount_percent > 0 and visit.discount_fixed > 0:
                raise ValidationError(_("You cannot use both Discount (%) and Discount (Fixed) at the same time. Please use only one."))

    def action_create_invoice(self):
        for visit in self:
            if visit.invoice_ids:
                raise UserError(_("An invoice already exists for this visit."))

            if not visit.owner_id:
                raise UserError(_("Please set an owner before creating an invoice."))

            partner = visit._get_or_create_partner_from_owner(visit.owner_id)
            if not partner:
                raise UserError(_("Could not create a partner for the owner."))

            invoice_lines = []
            first_account_id = False

            Account = self.env['account.account']
            if 'account_type' in Account._fields:
                income_account = Account.search([('account_type', '=', 'income')], limit=1)
            else:
                income_account = Account.search([('user_type_id.type', '=', 'income')], limit=1)
            if income_account:
                first_account_id = income_account.id

            def _get_income_account_for_product(product):
                if not product:
                    return None
                tmpl = product.product_tmpl_id
                return (
                    product.property_account_income_id.id
                    or (tmpl.property_account_income_id.id if tmpl and tmpl.property_account_income_id else False)
                    or (
                        tmpl.categ_id.property_account_income_categ_id.id
                        if tmpl and tmpl.categ_id and tmpl.categ_id.property_account_income_categ_id
                        else False
                    )
                )

            all_visit_lines = visit.service_line_ids + visit.test_line_ids + visit.medicine_line_ids

            test_lines = visit.test_line_ids.filtered(lambda l: l.product_id and l.quantity > 0 and l.service_id.is_combo)
            if test_lines:
                _logger.info("Visit %s: Combo test products detected, opening combo selection wizard", visit.name)
                return {
                    'name': _("Select Combo Components"),
                    'type': 'ir.actions.act_window',
                    'res_model': 'vet.test.combo.selection.wizard',
                    'view_mode': 'form',
                    'target': 'new',
                    'context': {
                        'default_visit_id': visit.id,
                        'default_test_line_ids': test_lines.ids,
                    },
                }

            for line in all_visit_lines:
                prod, qty, price = line.product_id, line.quantity or 1.0, line.price_unit or 0.0
                if not prod or not qty or not price:
                    _logger.warning(
                        "Visit %s: Skipping line %s (type=%s, product=%s, qty=%s, price=%s) due to invalid product/qty/price",
                        visit.name, line.id, line.service_id.service_type, prod.display_name if prod else 'None', qty, price
                    )
                    continue

                account_id = _get_income_account_for_product(prod) or first_account_id
                if not account_id:
                    _logger.error("Visit %s: No income account for product %s, using fallback account if available", visit.name, prod.display_name)
                    if not first_account_id:
                        raise UserError(
                            _("Please configure an Income Account for product %s.") % (prod.display_name)
                        )
                    account_id = first_account_id

                if not first_account_id:
                    first_account_id = account_id

                discount_val = visit.discount_percent if visit.discount_percent > 0 else 0.0

                invoice_lines.append((0, 0, {
                    'product_id': prod.id,
                    'name': prod.display_name,
                    'quantity': qty,
                    'price_unit': price,
                    'account_id': account_id,
                    'tax_ids': [(6, 0, prod.taxes_id.ids)],
                    'discount': discount_val,
                }))
                _logger.debug("Invoice line: product=%s, qty=%s, price=%s, discount=%s, account=%s",
                             prod.display_name, qty, price, discount_val, account_id)

            if visit.treatment_charge and float(visit.treatment_charge) != 0.0:
                if not first_account_id:
                    raise UserError(_("Cannot determine an income account for Treatment Charge."))
                invoice_lines.append((0, 0, {
                    'product_id': False,
                    'name': _("Treatment Charge"),
                    'quantity': 1.0,
                    'price_unit': float(visit.treatment_charge),
                    'account_id': first_account_id,
                    'tax_ids': [(6, 0, [])],
                }))
                _logger.debug("Invoice line for treatment charge: qty=1.0, price=%s", visit.treatment_charge)

            if visit.discount_fixed > 0:
                if not first_account_id:
                    raise UserError(_("Please configure an Income Account for discounts."))
                invoice_lines.append((0, 0, {
                    'product_id': False,
                    'name': _("Discount (Fixed)"),
                    'quantity': 1.0,
                    'price_unit': -float(visit.discount_fixed),
                    'account_id': first_account_id,
                    'tax_ids': [(6, 0, [])],
                }))
                _logger.debug("Invoice line for fixed discount: qty=1.0, price=%s", -float(visit.discount_fixed))

            if not invoice_lines:
                raise UserError(_("No invoiceable lines found for this visit. To pay previous balances, use the Complete Payment action."))

            invoice_vals = {
                'partner_id': partner.id,
                'move_type': 'out_invoice',
                'invoice_line_ids': invoice_lines,
                'invoice_date': fields.Date.context_today(self),
                'invoice_origin': visit.name,
                'visit_id': visit.id,
            }
            invoice = self.env['account.move'].create(invoice_vals)

            missing_account_lines = invoice.invoice_line_ids.filtered(lambda l: not l.account_id)
            if missing_account_lines:
                fallback = invoice.invoice_line_ids.filtered('account_id')[:1].account_id.id
                if fallback:
                    missing_account_lines.write({'account_id': fallback})
                else:
                    raise UserError(_("Invoice created but some lines have no account. Configure income accounts."))

            invoice.action_post()
            visit.with_context(skip_visit_validation=True).write({'invoice_ids': [(4, invoice.id)]})
            _logger.info("Invoice %s created and posted for visit %s", invoice.name, visit.name)
            visit.with_context(skip_visit_validation=True)._sync_state_with_payment()

            # Process delivery for all products (medicine and test lines)
            deliverable_lines = visit.line_ids.filtered(
                lambda l: l.product_id and l.quantity > 0
            )
            if deliverable_lines:
                try:
                    visit.action_deliver_products()
                    _logger.info("Visit %s: All product delivery processed successfully", visit.name)
                except Exception as e:
                    _logger.warning("Visit %s: Product delivery failed, proceeding with invoice creation: %s", visit.name, str(e).replace('_', 'underscore'))

            return True

    def action_deliver_products(self):
        StockPicking = self.env['stock.picking']
        StockMove = self.env['stock.move']
        try:
            StockLotModel = self.env['stock.lot']
        except KeyError:
            StockLotModel = self.env['stock.production.lot']

        for visit in self:
            if visit.delivered:
                _logger.info("Visit %s already delivered, skipping", visit.name)
                continue

            deliverable_lines = visit.line_ids.filtered(
                lambda l: l.product_id and l.quantity > 0 and not l.delivered
            )

            if not deliverable_lines:
                visit.delivered = True
                continue

            warehouse = self.env.user._get_default_warehouse_id()
            if not warehouse or not warehouse.out_type_id or not warehouse.lot_stock_id:
                raise UserError(_("Please configure the default warehouse with an Outgoing Shipments type and a stock location."))
            picking_type = warehouse.out_type_id
            dest_location = self.env.ref('stock.stock_location_customers', raise_if_not_found=False)
            if not dest_location:
                raise UserError(_("The 'Customers' stock location could not be found."))

            picking = StockPicking.create({
                'picking_type_id': picking_type.id,
                'location_id': warehouse.lot_stock_id.id,
                'location_dest_id': dest_location.id,
                'origin': f"Visit {visit.name}",
                'partner_id': visit.owner_id and visit._get_or_create_partner_from_owner(visit.owner_id).id or False,
            })

            for line in deliverable_lines:
                move = StockMove.create({
                    'name': line.product_id.display_name,
                    'product_id': line.product_id.id,
                    'product_uom_qty': line.quantity,
                    'product_uom': line.product_id.uom_id.id,
                    'picking_id': picking.id,
                    'location_id': picking.location_id.id,
                    'location_dest_id': picking.location_dest_id.id,
                })
                lot_id = False
                if line.product_id.tracking in ('lot', 'serial'):
                    lot_name = f"{visit.name}-{line.product_id.default_code or line.product_id.id}-{uuid.uuid4().hex[:8]}"
                    lot = StockLotModel.create({
                        'name': lot_name,
                        'product_id': line.product_id.id,
                        'company_id': self.env.company.id,
                    })
                    lot_id = lot.id
                self.env['stock.move.line'].create({
                    'move_id': move.id,
                    'picking_id': picking.id,
                    'product_id': line.product_id.id,
                    'product_uom_id': line.product_id.uom_id.id,
                    'quantity': line.quantity,
                    'qty_done': line.quantity,
                    'location_id': picking.location_id.id,
                    'location_dest_id': picking.location_dest_id.id,
                    'lot_id': lot_id,
                })

            try:
                picking.action_confirm()
                picking.action_assign()
                res = picking.button_validate()
                if isinstance(res, dict):
                    _logger.warning("Visit %s: Backorder created for picking %s.", visit.name, picking.name)
                else:
                    _logger.info("Visit %s: Stock picking %s validated successfully.", visit.name, picking.name)

                if picking.state == 'done':
                    deliverable_lines.write({'delivered': True})
                    visit.delivered = True
            except Exception as e:
                picking.unlink()
                _logger.error("Visit %s: Failed to validate stock picking %s: %s", visit.name, picking.name, str(e))
                raise UserError(_("Failed to process delivery for visit %s: %s") % (visit.name, str(e)))

        return True

    def action_pay_invoice(self):
        self.ensure_one()
        if not self.invoice_ids:
            raise UserError(_("No invoice found for this visit."))

        invoices = self.invoice_ids.filtered(lambda inv: inv.payment_state in ["not_paid", "partial"])
        if not invoices:
            raise UserError(_("All invoices are already paid."))

        unpaid_balance = self._get_owner_unpaid_balance()

        return {
            "name": _("Register Payment"),
            "type": "ir.actions.act_window",
            "res_model": "vet.animal.visit.payment.wizard",
            "view_mode": "form",
            "target": "new",
            'context': {
                "default_visit_id": self.id,
                "default_owner_unpaid_balance": unpaid_balance,
                "default_amount": unpaid_balance,
            },
        }

    def action_view_invoices(self):
        self.ensure_one()
        if not self.invoice_ids:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _("No Invoices"),
                    'message': _("No invoices exist for this visit."),
                    'sticky': False
                }
            }
        return {
            'name': _("Invoices"),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'views': [
                (
                    self.env.ref('vet_test.view_vet_animal_visit_invoice_list').id, 'list'
                ) if self.env.ref('vet_test.view_vet_animal_visit_invoice_list', False) else (False, 'list'),
                (
                    self.env.ref('vet_test.view_vet_animal_visit_invoice_form').id, 'form'
                ) if self.env.ref('vet_test.view_vet_animal_visit_invoice_form', False) else (False, 'form')
            ],
            'domain': [('id', 'in', self.invoice_ids.ids)],
            'context': {'default_visit_id': self.id},
        }

    @api.onchange('owner_id')
    def _onchange_owner_selected_animals(self):
        if self.owner_id:
            return {'domain': {'selected_animal_id': [('owner_id', '=', self.owner_id.id)]}}
        return {'domain': {'selected_animal_id': []}}

    @api.onchange('selected_animal_id')
    def _onchange_selected_animal_id(self):
        if self.selected_animal_id:
            self.animal_id = self.selected_animal_id
            self.animal_name = self.selected_animal_id
            self.owner_id = self.selected_animal_id.owner_id
            self.contact_number = self.selected_animal_id.owner_id.contact_number or ''
            self.animal_ids = self.env['vet.animal'].search([('owner_id', '=', self.owner_id.id)])
        else:
            self.animal_id = False
            self.animal_name = ''
            self.owner_id = False
            self.contact_number = ''
            self.animal_ids = False

    @api.onchange('animal_name')
    def _onchange_animal_name(self):
        if self.animal_name:
            self.animal_id = self.animal_name
            self.selected_animal_id = self.animal_name
            self.owner_id = self.animal_name.owner_id
            self.contact_number = self.animal_name.owner_id.contact_number or ''
        else:
            self.animal_id = False
            self.selected_animal_id = False
            self.owner_id = False
            self.contact_number = ''

    def action_complete_payment(self):
        self.ensure_one()
        if not self.invoice_ids:
            raise UserError(_("No invoice found for this visit."))

        partner = self.owner_id.partner_id
        invoices = self.env['account.move'].search([
            ('partner_id', '=', partner.id),
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('payment_state', 'in', ['not_paid', 'partial']),
        ], order='invoice_date asc, id asc')

        if not invoices:
            raise UserError(_("No unpaid invoices found for this owner."))

        return {
            'name': _('Register Payment'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.payment.register',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_model': 'account.move',
                'active_ids': invoices.ids,
                'default_partner_id': partner.id,
                'default_amount': sum(invoices.mapped('amount_residual')),
                'default_payment_type': 'inbound',
                'default_partner_type': 'customer',
            }
        }

class VetAnimal(models.Model):
    _inherit = "vet.animal"

    def name_get(self):
        result = []
        for animal in self:
            parts = []
            if animal.microchip_no:
                parts.append(f"#{animal.microchip_no}")
            if animal.name:
                parts.append(animal.name)
            if animal.owner_id:
                parts.append(f"Owner: {animal.owner_id.name}")
                if animal.owner_id.contact_number:
                    parts.append(f"Phone: {animal.owner_id.contact_number}")
            display = " | ".join(parts)
            result.append((animal.id, display))
        return result

    @api.model
    def name_search(self, name='', args=None, operator='ilike', limit=100):
        args = args or []
        name = (name or '').strip()
        if not name:
            return self.search(args, limit=limit).name_get()
        if name.startswith('#'):
            chip = name[1:].strip()
            domain = [('microchip_no', '=', chip)]
        else:
            domain = ['|', ('microchip_no', operator, name), ('name', operator, name)]
        try:
            records = self.search(domain + args, limit=limit)
            return records.name_get()
        except Exception as exc:
            _logger.exception("vet.animal.name_search failed: %s", exc)
            return []

    def action_view_invoices(self):
        self.ensure_one()
        return {
            'name': 'Invoices',
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'views': [
                (
                    self.env.ref('vet_test.view_vet_animal_visit_invoice_list').id, 'list'
                ) if self.env.ref('vet_test.view_vet_animal_visit_invoice_list', False) else (False, 'list'),
                (
                    self.env.ref('vet_test.view_vet_animal_visit_invoice_form').id, 'form'
                ) if self.env.ref('vet_test.view_vet_animal_visit_invoice_form', False) else (False, 'form')
            ],
            'domain': [('visit_id', 'in', self.env['vet.animal.visit'].search([('animal_id', '=', self.id)]).ids), ('payment_state', '!=', 'paid')],
            'context': {'create': False},
        }

class VetTestComboSelectionWizard(models.Model):
    _name = 'vet.test.combo.selection.wizard'
    _description = 'Select Components for Test Combo'

    visit_id = fields.Many2one('vet.animal.visit', string="Visit", readonly=True, required=True)
    test_line_ids = fields.Many2many('vet.animal.visit.line', string="Test Lines", readonly=True)
    line_ids = fields.One2many('vet.test.combo.selection.wizard.line', 'wizard_id', string="Components")

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        context = self.env.context
        visit_id = context.get('default_visit_id')
        if visit_id:
            visit = self.env['vet.animal.visit'].browse(visit_id)
            test_line_ids = context.get('default_test_line_ids', [])
            test_lines = self.env['vet.animal.visit.line'].browse(test_line_ids)
            res.update({
                'visit_id': visit.id,
                'test_line_ids': [(6, 0, test_line_ids)],
            })

            wizard_lines = []
            for line in test_lines.filtered(lambda l: l.service_id.is_combo):
                product = line.product_id
                combo_components = product.combo_product_ids  # Assuming combo_product_ids is a Many2many field on product.product
                if not combo_components:
                    wizard_lines.append((0, 0, {
                        'combo_product_id': product.id,
                        'component_product_id': product.id,
                        'quantity_to_deliver': line.quantity,
                        'product_uom_id': product.uom_id.id,
                    }))
                else:
                    for component in combo_components:
                        wizard_lines.append((0, 0, {
                            'combo_product_id': product.id,
                            'component_product_id': component.id,
                            'quantity_to_deliver': line.quantity,
                            'product_uom_id': component.uom_id.id,
                        }))
            res['line_ids'] = wizard_lines
        return res

    def action_process(self):
        self.ensure_one()
        visit = self.visit_id
        new_lines = []
        for wizard_line in self.line_ids:
            if wizard_line.quantity_to_deliver <= 0:
                continue
            new_lines.append((0, 0, {
                'visit_id': visit.id,
                'service_id': wizard_line.combo_product_id.service_id.id,  # Assuming service_id on product
                'product_id': wizard_line.component_product_id.id,
                'quantity': wizard_line.quantity_to_deliver,
                'price_unit': wizard_line.component_product_id.lst_price,
                'service_type': 'test',
            }))
        if new_lines:
            visit.with_context(skip_visit_validation=True).write({'line_ids': new_lines})
            _logger.info("Visit %s: Added %s component lines from combo selection", visit.name, len(new_lines))
        visit.action_create_invoice()
        return {'type': 'ir.actions.act_window_close'}

class VetTestComboSelectionWizardLine(models.Model):
    _name = 'vet.test.combo.selection.wizard.line'
    _description = 'Line for Test Combo Selection Wizard'

    wizard_id = fields.Many2one('vet.test.combo.selection.wizard', required=True, ondelete='cascade')
    combo_product_id = fields.Many2one('product.product', string="Test/Combo", readonly=True)
    component_product_id = fields.Many2one('product.product', string="Component", required=True)
    quantity_to_deliver = fields.Float(string="Quantity", default=1.0, required=True)
    product_uom_id = fields.Many2one('uom.uom', string="Unit of Measure", required=True)
    available_quantity = fields.Float(related='component_product_id.qty_available', string="On Hand")

class VetAnimalVisitPaymentWizard(models.Model):
    _name = "vet.animal.visit.payment.wizard"
    _description = "Vet Animal Visit Payment Wizard"

    journal_id = fields.Many2one(
        "account.journal",
        string="Journal",
        domain="[('type', 'in', ('cash', 'bank'))]",
        required=True,
    )
    amount = fields.Float(
        string="Payment Amount",
        required=True
    )
    visit_id = fields.Many2one(
        'vet.animal.visit',
        string="Visit",
        required=True
    )
    payment_method = fields.Selection(
        [('cash', 'Cash'), ('bank', 'Bank')],
        string="Payment Method",
        default='cash'
    )
    owner_unpaid_balance = fields.Float(
        string="Unpaid Balance",
        compute="_compute_owner_unpaid_balance",
        store=False,
        digits=(16, 2),
    )

    @api.model
    def default_get(self, fields_list):
        res = super(VetAnimalVisitPaymentWizard, self).default_get(fields_list)
        if 'visit_id' in res and res['visit_id']:
            visit = self.env['vet.animal.visit'].browse(res['visit_id'])
            if visit.owner_id and visit.owner_id.partner_id:
                res['owner_unpaid_balance'] = visit._get_owner_unpaid_balance()
                if 'amount' not in res or not res['amount']:
                    res['amount'] = res['owner_unpaid_balance']
        return res

    @api.onchange('payment_method')
    def _onchange_payment_method(self):
        if self.payment_method:
            domain = [('type', '=', self.payment_method)]
            journal = self.env['account.journal'].search(domain, limit=1)
            if journal:
                self.journal_id = journal
            return {'domain': {'journal_id': domain}}
        return {'domain': {'journal_id': [('type', 'in', ('cash', 'bank'))]}}

    @api.onchange('visit_id')
    def _onchange_visit_id(self):
        if self.visit_id and self.visit_id.owner_id and self.visit_id.owner_id.partner_id:
            self.owner_unpaid_balance = self.visit_id._get_owner_unpaid_balance()
            self.amount = self.owner_unpaid_balance
        else:
            self.owner_unpaid_balance = 0.0
            self.amount = 0.0

    def action_confirm_payment(self):
        self.ensure_one()
        visit = self.env['vet.animal.visit'].browse(self.visit_id.id)
        if not visit.exists():
            raise UserError(_("The visit record does not exist or has been deleted."))
        partner = visit.owner_id.partner_id
        if not partner:
            raise UserError(_("Visit owner has no linked partner. Cannot process payment."))
        if not partner.property_account_receivable_id:
            raise UserError(_("Partner %s has no receivable account configured.") % partner.name)
        if not self.journal_id or not self.journal_id.default_account_id:
            raise UserError(_("Selected journal has no default account configured."))

        journal_account = self.journal_id.default_account_id
        expected_account_type = 'asset_cash'
        if journal_account.account_type != expected_account_type:
            raise UserError(
                _("Journal %s has an incorrect default account type. Expected '%s', found '%s'. Please configure the correct account.") %
                (self.journal_id.name, expected_account_type, journal_account.account_type)
            )

        amount = self.amount
        if amount <= 0:
            raise UserError(_("Payment amount must be greater than zero."))

        invoices = self.env['account.move'].search([
            ('partner_id', '=', partner.id),
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('payment_state', 'in', ['not_paid', 'partial']),
        ], order='invoice_date asc, id asc')

        if not invoices:
            raise UserError(_("No unpaid invoices found for this owner."))

        total_residual = sum(invoices.mapped('amount_residual'))
        if amount > total_residual:
            raise UserError(
                _("You are trying to pay more (%.2f) than the total unpaid balance (%.2f).") % (amount, total_residual)
            )

        visit.with_context(from_payment_wizard=True).write({'latest_payment_amount': amount, 'payment_method': self.payment_method})

        _logger.info("Visit %s: Updated latest_payment_amount to %s", visit.name, amount)

        payments = self.env['account.payment']
        remaining_amount = amount

        try:
            for invoice in invoices:
                if remaining_amount <= 0:
                    break
                payment_amount = min(remaining_amount, invoice.amount_residual)
                if payment_amount <= 0:
                    continue

                PaymentRegister = self.env['account.payment.register']
                ctx = {
                    'active_model': 'account.move',
                    'active_ids': [invoice.id],
                    'default_amount': payment_amount,
                    'default_partner_id': partner.id,
                    'default_payment_type': 'inbound',
                    'default_partner_type': 'customer',
                    'default_journal_id': self.journal_id.id,
                    'default_payment_reference': f"Payment for {visit.name} - Invoice {invoice.name}",
                }
                _logger.debug("Visit %s: Processing payment of %s for invoice %s", visit.name, payment_amount, invoice.name)
                payment_wizard = PaymentRegister.with_context(ctx).create({})
                payment_wizard.payment_difference_handling = 'reconcile' if payment_amount >= invoice.amount_residual else 'open'
                payment_result = payment_wizard._create_payments()
                new_payment = payment_result if isinstance(payment_result, self.env['account.payment']) else self.env['account.payment'].browse(payment_result.ids)
                payments |= new_payment
                remaining_amount -= payment_amount
                _logger.info("Visit %s: Payment of %s registered for invoice %s", visit.name, payment_amount, invoice.name)

            if remaining_amount > 0:
                _logger.warning("Visit %s: Payment amount %s not fully allocated", visit.name, remaining_amount)

        except Exception as e:
            _logger.warning("Standard payment register failed for visit %s: %s", visit.name, str(e))
            remaining_amount = self.amount
            for invoice in invoices:
                if remaining_amount <= 0:
                    break
                payment_amount = min(remaining_amount, invoice.amount_residual)
                if payment_amount <= 0:
                    continue

                payment_move = self.env["account.move"].create({
                    'move_type': 'entry',
                    'date': fields.Date.context_today(self),
                    'ref': f"Payment for {visit.name} - Invoice {invoice.name}",
                    'journal_id': self.journal_id.id,
                    'line_ids': [
                        (0, 0, {
                            'name': f"Payment for {visit.name} - Invoice {invoice.name}",
                            'debit': 0.0,
                            'credit': payment_amount,
                            'account_id': partner.property_account_receivable_id.id,
                            'partner_id': partner.id,
                        }),
                        (0, 0, {
                            'name': f"Cash/Bank for {visit.name} - Invoice {invoice.name}",
                            'debit': payment_amount,
                            'credit': 0.0,
                            'account_id': self.journal_id.default_account_id.id,
                            'partner_id': partner.id,
                        }),
                    ],
                })
                payment_move.action_post()
                _logger.info("Visit %s: Manual journal entry created for invoice %s: %s", visit.name, invoice.name, payment_move.name)

                receivable_line = invoice.line_ids.filtered(
                    lambda l: l.account_id == partner.property_account_receivable_id and not l.reconciled
                )
                payment_line = payment_move.line_ids.filtered(
                    lambda l: l.account_id == partner.property_account_receivable_id
                )
                if receivable_line and payment_line:
                    try:
                        (receivable_line + payment_line).reconcile()
                        _logger.info("Visit %s: Fallback reconciliation successful for invoice %s", visit.name, invoice.name)
                    except Exception as e:
                        _logger.error("Visit %s: Fallback reconciliation failed for invoice %s: %s", visit.name, invoice.name, e)

                remaining_amount -= payment_amount

        invoices._compute_payment_state()
        invoices.invalidate_recordset(['payment_state', 'amount_residual'])
        visit.invalidate_recordset(['payment_state', 'is_fully_paid', 'amount_received'])
        visit.with_context(skip_visit_validation=True)._sync_state_with_payment()
        _logger.info(
            "Visit %s: Post-payment - State=%s, payment_state=%s, is_fully_paid=%s, amount_received=%s, invoice_residual=%s",
            visit.name, visit.state, visit.payment_state, visit.is_fully_paid, visit.amount_received,
            sum(invoices.mapped('amount_residual'))
        )

        return self._generate_receipt(visit, invoices, payments[0] if payments else None)

    def _generate_receipt(self, visit, invoices, payment=None):
        try:
            payments = self.env['account.payment'].search([
                ('payment_reference', 'ilike', visit.name),
                ('state', '=', 'posted'),
                ('date', '>=', fields.Date.context_today(self)),
            ], order='create_date desc', limit=1)
            if payments:
                _logger.info("Visit %s: Generating payment receipt for payment %s", visit.name, payments.name)
                return self.env.ref('account.account_payment_receipt_action').report_action(payments)
        except Exception as e:
            _logger.warning("Payment receipt not available for visit %s: %s", visit.name, e)
        try:
            _logger.info("Visit %s: Falling back to visit receipt", visit.name)
            return self.env.ref('vet_test.action_report_visit_receipt').report_action(visit)
        except Exception as e:
            _logger.error("Receipt generation failed for visit %s: %s", visit.name, e)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Payment Successful'),
                    'message': _('Payment of %s was processed successfully.') % self.amount,
                    'sticky': False,
                }
            }

class ReportVisitReceipt(models.AbstractModel):
    _name = 'report.vet_test.report_visit_receipt'
    _description = 'Visit Receipt Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['vet.animal.visit'].browse(docids)
        for doc in docs:
            _logger.info("Generating receipt for visit %s: subtotal=%s, total_amount=%s", doc.name, doc.subtotal, doc.total_amount)
            total_amount = doc.total_amount
            receipt_lines = doc.receipt_lines
            for line in receipt_lines:
                _logger.debug("Receipt line for visit %s: product=%s, quantity=%s, price_unit=%s, subtotal=%s",
                              doc.name, line.product_id.display_name, line.quantity, line.price_unit, line.subtotal)
        return {
            'doc_ids': docs.ids,
            'doc_model': 'vet.animal.visit',
            'docs': docs,
            'subtotal': lambda doc: doc.subtotal,
            'total_amount': lambda doc: doc.total_amount,
            'receipt_lines': lambda doc: doc.receipt_lines,
        }
