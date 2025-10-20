from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import re

def _normalize_phone(phone):
    return re.sub(r'\D', '', str(phone or ''))

class VetAnimalDoctor(models.Model):
    _name = 'vet.animal.doctor'
    _description = 'Animal Doctor'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char("Doctor Name", required=True, tracking=True)
    contact_number = fields.Char("Contact Number", tracking=True, index=True)
    email = fields.Char("Email", tracking=True)
    specialization = fields.Char("Specialization", tracking=True)
    appointments = fields.One2many('vet.animal.schedule', 'doctor_id', string="Appointments")
    active = fields.Boolean(default=True)
    visit_ids = fields.One2many('vet.animal.visit', 'doctor_id', string='Visits')
    notes = fields.Text("Notes")
    
    # ✅ NEW FIELD: Assign doctor to a specific branch (analytic account)
    analytic_account_id = fields.Many2one(
        'account.analytic.account',
        string="Branch",
        required=True,  # Make it required to enforce branch assignment; remove if optional
        tracking=True,
        help="The branch this doctor is assigned to."
    )

    _sql_constraints = [
        ('unique_contact_number_doctor', 'unique(contact_number)', 'Contact number must be unique among doctors!')
    ]

    @api.model_create_multi
    def create(self, vals_list):
        # normalize phone in incoming vals so DB stores digits-only
        for vals in vals_list:
            if 'contact_number' in vals and vals.get('contact_number'):
                vals['contact_number'] = _normalize_phone(vals['contact_number'])
        return super().create(vals_list)

    def write(self, vals):
        if 'contact_number' in vals and vals.get('contact_number') is not None:
            vals['contact_number'] = _normalize_phone(vals['contact_number'])
        return super().write(vals)

    @api.constrains('contact_number')
    def _check_unique_contact_across_models(self):
        for record in self:
            phone = _normalize_phone(record.contact_number)
            if not phone:
                # If you want a phone mandatory for doctors, raise here instead.
                continue

            # 1) Validate length = exactly 11 digits
            if len(phone) != 11:
                raise ValidationError(_("Contact number must be exactly 11 digits."))

            # 2) Check other doctors (normalized)
            dup = self.search([('id', '!=', record.id), ('contact_number', '!=', False)])
            for d in dup:
                if _normalize_phone(d.contact_number) == phone:
                    raise ValidationError(_("This contact number is already used by another doctor."))

            # 3) Check animal owners (normalized)
            owners = self.env['vet.animal.owner'].search([('contact_number', '!=', False)])
            for o in owners:
                if _normalize_phone(o.contact_number) == phone:
                    raise ValidationError(_("This contact number is already used by an animal owner."))

            # 4) Check res.partner (contacts), skip companies and backend users
            partners = self.env['res.partner'].search([
                ('phone', '!=', False),
                ('is_company', '=', False),
            ])
            for p in partners:
                # skip partners that are linked to system users
                if p.user_ids:
                    continue
                if _normalize_phone(p.phone) == phone:
                    raise ValidationError(_("This contact number is already used by a contact."))

class AccountAnalyticAccount(models.Model):
    _inherit = 'account.analytic.account'
    image = fields.Image(string="Image", max_width=128, max_height=128)
    
    # ✅ UPDATED: Now uses vet.animal.doctor, filters by branch, defaults doctor_id (not employee_id)
    def action_open_register(self):
        """🚨 GULSHAN LOCK + FILTER - NO CHOICE NEEDED!"""
        self.ensure_one()
        
        # ✅ STEP 1: LOCK USER TO THIS BRANCH ONLY
        self.env.user.write({'analytic_account_ids': [(6, 0, [self.id])]})
        
        # ✅ STEP 2: GET GULSHAN DOCTORS ONLY (from vet.animal.doctor, not hr.employee)
        gulshan_doctors = self.env['vet.animal.doctor'].search([
            ('analytic_account_id', '=', self.id),  # Doctors assigned to this branch only
            ('active', '=', True)                   # Optional: only active doctors
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
                'default_doctor_id': (gulshan_doctors[0].id if gulshan_doctors else False), # Default GULSHAN DOCTOR (changed from employee_id)
                'search_default_analytic_account_id': self.id,    # Filter list = GULSHAN ONLY
                'search_default_my_visits': 1,                    # Show only my visits
                'default_group_by': 'doctor_id',                  # Group by GULSHAN DOCTORS (changed from employee_id)
            },
        }
