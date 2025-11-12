from odoo import api, fields, models
import logging
_logger = logging.getLogger(__name__)
class VetAnimalHistoryService(models.TransientModel):
    _name = "vet.animal.history.service"
    _description = "Animal Visit History Service"
    _inherit = ['ir.autovacuum']
    _transient_max_hours = 24

    history_line_id = fields.Many2one("vet.animal.history.line", string="History Line", ondelete="cascade")
    name = fields.Char(string="Service/Treatment")
    amount = fields.Float(string="Amount")
class VetAnimalHistoryLine(models.TransientModel):
    _name = "vet.animal.history.line"
    _description = "Animal Visit History Line"
    _inherit = ['ir.autovacuum']
    _transient_max_hours = 24

    wizard_id = fields.Many2one("vet.animal.history.wizard", string="Wizard", ondelete="cascade")
    visit_id = fields.Many2one("vet.animal.visit", string="Visit")
    visit_date = fields.Datetime(string="Visit Date")
    doctor = fields.Char(string="Doctor")
    notes = fields.Text(string="Notes")
    total_amount = fields.Float(string="Total Amount")
    service_line_ids = fields.One2many("vet.animal.history.service", "history_line_id", string="Services/Treatments")
    service_names = fields.Char(string="Services/Treatments", compute="_compute_service_names", store=False)

    @api.depends('service_line_ids')
    def _compute_service_names(self):
        for line in self:
            services = [f"{s.name} (${s.amount:.2f})" for s in line.service_line_ids]
            line.service_names = ", ".join(services) or "N/A"

class VetAnimalHistoryWizard(models.TransientModel):
    _name = "vet.animal.history.wizard"
    _description = "Animal Visit History Search"

    # ─────────────────────────────────────────────
    # 🔹 Owner Info Section (New Fields)
    # ─────────────────────────────────────────────
    owner_id = fields.Many2one("res.partner", string="Owner")
    contact_number = fields.Char(string="Owner Contact")
    animal_ids = fields.Many2many("vet.animal", string="Owner's Animals", compute="_compute_animal_ids", store=False)
    selected_animal_id = fields.Many2one("vet.animal", string="Select Animal")
    owner_unpaid_balance = fields.Float(string="Unpaid Balance", compute="_compute_unpaid_balance", store=False)

    # ─────────────────────────────────────────────
    # 🔹 Animal Search Section (Existing)
    # ─────────────────────────────────────────────
    animal_id = fields.Many2one("vet.animal", string="Animal")
    animal_name = fields.Char(string="Animal Name", readonly=False)
    partner_id = fields.Many2one("res.partner", string="Owner (Legacy)")
    history_line_ids = fields.One2many("vet.animal.history.line", "wizard_id", string="History Lines")
    service_name = fields.Char(string="Service/Treatment", compute="_compute_service_name", store=False)
    total_visits = fields.Integer(string="Total Visits", readonly=True)

    # ─────────────────────────────────────────────
    # 🔹 Computed Fields
    # ─────────────────────────────────────────────
    def _compute_service_name(self):
        for rec in self:
            rec.service_name = False

    @api.depends("owner_id")
    def _compute_animal_ids(self):
        for rec in self:
            if rec.owner_id:
                rec.animal_ids = self.env["vet.animal"].search([("owner_id.partner_id", "=", rec.owner_id.id)])
            else:
                rec.animal_ids = False

    @api.depends("owner_id")
    def _compute_unpaid_balance(self):
        """Compute owner's unpaid invoices (open state). Only include posted invoices."""
        for rec in self:
            if rec.owner_id:
                invoices = self.env["account.move"].search([
                    ("partner_id", "=", rec.owner_id.id),
                    ("move_type", "=", "out_invoice"),
                    ("state", "=", "posted"),  # ← Only posted (valid) invoices
                    ("payment_state", "in", ["not_paid", "partial"])
                ])
                rec.owner_unpaid_balance = sum(invoices.mapped("amount_residual"))
            else:
                rec.owner_unpaid_balance = 0.0

    # ─────────────────────────────────────────────
    # 🔹 Onchange Handlers
    # ─────────────────────────────────────────────
    @api.onchange("owner_id")
    def _onchange_owner(self):
        """Update contact and animal list when owner changes."""
        if self.owner_id:
            self.contact_number = self.owner_id.phone
            self.animal_ids = self.env["vet.animal"].search([("owner_id.partner_id", "=", self.owner_id.id)])
        else:
            self.contact_number = False
            self.animal_ids = False
            self.selected_animal_id = False

    @api.onchange('contact_number')
    def _onchange_contact_number(self):
        self.owner_id = False
        self.animal_id = False

        if self.contact_number:
            owner = self.env['vet.animal.owner'].search([
                ('contact_number', '=', self.contact_number.strip())
            ], limit=1)

            if owner:
                # 🔹 FIX: assign the partner linked to the owner
                self.owner_id = owner.partner_id

                animals = self.env['vet.animal'].search([('owner_id', '=', owner.id)])
                if len(animals) == 1:
                    self.animal_id = animals[0]

                domain = {'animal_id': [('owner_id', '=', owner.id)]}
            else:
                domain = {'animal_id': [('id', '!=', False)]}
        else:
            domain = {'animal_id': [('id', '!=', False)]}

        return {
            'domain': domain,
            'value': {
                'owner_id': self.owner_id.id if self.owner_id else False,
                'animal_id': self.animal_id.id if self.animal_id else False
            }
        }

    @api.onchange("selected_animal_id")
    def _onchange_selected_animal(self):
        """Sync selected_animal_id with animal_id (for search logic)."""
        if self.selected_animal_id:
            self.animal_id = self.selected_animal_id
            self.animal_name = self.selected_animal_id.name
        else:
            self.animal_id = False

    # ─────────────────────────────────────────────
    # 🔹 History Search Logic (unchanged)
    # ─────────────────────────────────────────────
    def action_search_history(self):
        self.ensure_one()
        _logger.info(
            "User %s running action_search_history with groups: %s",
            self.env.user.name, self.env.user.groups_id.mapped("name"),
        )

        domain = []

        if self.animal_id:
            domain.append(("animal_id", "=", self.animal_id.id))
        elif self.animal_name:
            animals = self.env["vet.animal"].search([("name", "ilike", self.animal_name)])
            domain.append(("animal_id", "in", animals.ids)) if animals else domain.append(("id", "=", 0))
        elif self.contact_number:
            owner = self.env["res.partner"].search([("phone", "=", self.contact_number)], limit=1)
            if owner:
                animals = self.env["vet.animal"].search([("owner_id.partner_id", "=", owner.id)])
                domain.append(("animal_id", "in", animals.ids)) if animals else domain.append(("id", "=", 0))
            else:
                domain.append(("id", "=", 0))

        visits = self.env["vet.animal.visit"].search(domain, order="date desc")
        _logger.info("Found %s visits for domain %s", len(visits), domain)

        lines = []
        for visit in visits:
            service_lines = []

            if visit.treatment_charge > 0:
                service_lines.append((0, 0, {
                    "name": "Treatment Charge",
                    "amount": visit.treatment_charge,
                }))

            for s in visit.service_line_ids.sudo():
                service_name = s.service_id.name or s.product_id.name or "Service Charge"
                service_lines.append((0, 0, {
                    "name": service_name,
                    "amount": s.subtotal,
                }))
                if s.service_id and s.service_id.product_id:
                    for product in s.service_id.product_id:
                        service_lines.append((0, 0, {
                            "name": f"{product.name} (via {s.service_id.name})",
                            "amount": product.lst_price or 0.0,
                        }))

            for test in visit.test_line_ids.sudo():
                test_name = test.service_id.name or test.product_id.name or "Unnamed Test"
                service_lines.append((0, 0, {
                    "name": test_name,
                    "amount": test.subtotal or 0.0,
                }))

            for vaccine in visit.medicine_line_ids.sudo():
                vaccine_name = vaccine.service_id.name or vaccine.product_id.name or "Unnamed Vaccine"
                service_lines.append((0, 0, {
                    "name": vaccine_name,
                    "amount": vaccine.subtotal or 0.0,
                }))

            _logger.info("Visit %s: Creating %s service lines", visit.name, len(service_lines))

            lines.append((0, 0, {
                "visit_id": visit.id,
                "visit_date": visit.date,
                "doctor": visit.doctor_id.name,
                "notes": visit.notes or "-",
                "total_amount": visit.total_amount,
                "service_line_ids": service_lines,
            }))

        self.history_line_ids = [(5, 0, 0)] + lines
        self.total_visits = len(visits)
        _logger.info("Wizard %s updated with %s lines (total %s visits)", self.id, len(lines), self.total_visits)

        return self._return_wizard_action()

    def _return_wizard_action(self):
        """Reopen wizard with updated results."""
        return {
            "type": "ir.actions.act_window",
            "res_model": "vet.animal.history.wizard",
            "view_mode": "form",
            "res_id": self.id,
            "target": "new",
        }




