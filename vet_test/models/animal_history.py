from odoo import api, fields, models
import logging
_logger = logging.getLogger(__name__)

class VetAnimalHistoryWizard(models.TransientModel):
    _name = "vet.animal.history.wizard"
    _description = "Animal Visit History Search"
    
    animal_id = fields.Many2one("vet.animal", string="Animal")
    animal_name = fields.Char(string="Animal Name", readonly=False)
    partner_id = fields.Many2one("res.partner", string="Owner")
    contact_number = fields.Char(string="Owner Contact")
    history_line_ids = fields.One2many("vet.animal.history.line", "wizard_id", string="History Lines")
    service_name = fields.Char(
        string="Service/Treatment",
        compute="_compute_service_name",
        store=False
    )
    total_visits = fields.Integer(string="Total Visits", readonly=True)

    def _compute_service_name(self):
        for rec in self:
            rec.service_name = False

    @api.onchange('partner_id')
    def _onchange_partner(self):
        if self.partner_id:
            self.contact_number = self.partner_id.phone

    @api.onchange('animal_id')
    def _onchange_animal(self):
        if self.animal_id and self.animal_id.owner_id:
            self.partner_id = self.animal_id.owner_id.partner_id
            self.contact_number = self.partner_id.phone
            self.animal_name = self.animal_id.name
        return {'domain': {'animal_id': [('id', '=', self.animal_id.id)]}}

    @api.onchange('animal_name')
    def _onchange_animal_name(self):
        if self.animal_name:
            animals = self.env['vet.animal'].search([('name', 'ilike', self.animal_name)])
            return {'domain': {'animal_id': [('id', 'in', animals.ids)]}}
        return {'domain': {'animal_id': [('id', '=', False)]}}

    @api.onchange('contact_number')
    def _onchange_contact_number(self):
        if self.contact_number:
            owner = self.env['res.partner'].search([('phone', '=', self.contact_number)], limit=1)
            if owner:
                self.partner_id = owner
                animals = self.env['vet.animal'].search([('owner_id.partner_id', '=', owner.id)])
                self.animal_id = False
                return {'domain': {'animal_id': [('id', 'in', animals.ids)]}}
            else:
                self.partner_id = False
                self.animal_id = False
                return {'domain': {'animal_id': [('id', '=', False)]}}
        else:
            self.partner_id = False
            self.animal_id = False
            return {'domain': {'animal_id': [('id', '=', False)]}}

    def action_search_history(self):
        self.ensure_one()
        _logger.info("User %s running action_search_history with groups: %s", self.env.user.name, self.env.user.groups_id.mapped('name'))
        domain = []
    
        if self.animal_id:
            domain.append(('animal_id', '=', self.animal_id.id))
        elif self.animal_name:
            animals = self.env['vet.animal'].search([('name', 'ilike', self.animal_name)])
            domain.append(('animal_id', 'in', animals.ids)) if animals else domain.append(('id', '=', 0))
        elif self.contact_number:
            owner = self.env['res.partner'].search([('phone', '=', self.contact_number)], limit=1)
            if owner:
                animals = self.env['vet.animal'].search([('owner_id.partner_id', '=', owner.id)])
                domain.append(('animal_id', 'in', animals.ids)) if animals else domain.append(('id', '=', 0))
            else:
                domain.append(('id', '=', 0))
    
        visits = self.env['vet.animal.visit'].search(domain, order='date desc')
        _logger.info("Found %s visits for domain %s", len(visits), domain)
    
        lines = []
        for visit in visits:
            service_lines = []
            # Add services from service_line_ids
            for s in visit.service_line_ids.sudo():
                if s.service_id or s.product_id:
                    service_lines.append((0, 0, {
                        'name': s.service_id.name or s.product_id.name or "N/A",
                        'amount': s.subtotal,
                    }))
                # Add products linked to the service
                if s.service_id and s.service_id.product_id:
                    for product in s.service_id.product_id:
                        service_lines.append((0, 0, {
                            'name': f"{product.name} (via {s.service_id.name})",
                            'amount': product.lst_price or 0.0,
                        }))
            
            # Add tests from test_line_ids
            for test in visit.test_line_ids.sudo():
                service_lines.append((0, 0, {
                    'name': test.service_id.name or test.product_id.name or "Unnamed Test",
                    'amount': test.subtotal or 0.0,
                }))
            
            # Add vaccines from medicine_line_ids
            for vaccine in visit.medicine_line_ids.sudo():
                service_lines.append((0, 0, {
                    'name': vaccine.service_id.name or vaccine.product_id.name or "Unnamed Vaccine",
                    'amount': vaccine.subtotal or 0.0,
                }))
            
            _logger.info("Visit %s: Creating %s service lines: %s", visit.name, len(service_lines), service_lines)
    
            line_vals = {
                'visit_id': visit.id,
                'visit_date': visit.date,
                'doctor': visit.doctor_id.name,
                'notes': visit.notes or '-',
                'total_amount': visit.total_amount,
                'service_line_ids': service_lines,
            }
            lines.append((0, 0, line_vals))
    
        # Reset before adding
        self.history_line_ids = [(5, 0, 0)] + lines
        self.total_visits = len(visits)
        _logger.info("Wizard %s: Updated history_line_ids with %s lines, total_visits=%s", self.id, len(lines), self.total_visits)
    
        return self._return_wizard_action()

    def _return_wizard_action(self):
        """Reopen wizard with updated results"""
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'vet.animal.history.wizard',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        }

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

class VetAnimalHistoryService(models.TransientModel):
    _name = "vet.animal.history.service"
    _description = "Animal Visit History Service"
    _inherit = ['ir.autovacuum']
    _transient_max_hours = 24

    history_line_id = fields.Many2one("vet.animal.history.line", string="History Line", ondelete="cascade")
    name = fields.Char(string="Service/Treatment")
    amount = fields.Float(string="Amount")
