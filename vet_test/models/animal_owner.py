from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import re
from dateutil.relativedelta import relativedelta

class VetAnimalOwner(models.Model):
    _name = 'vet.animal.owner'
    _description = 'Animal Owner'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    partner_id = fields.Many2one('res.partner', string="Contact", required=True, ondelete="cascade")
    notes = fields.Text("Additional Notes")
    active = fields.Boolean("Active", default=True)

    name = fields.Char(related="partner_id.name", store=True, readonly=False, tracking=True, index=True)
    contact_number = fields.Char(related="partner_id.phone", store=True, readonly=False, tracking=True, index=True,
        search=lambda self, operator, value: [('partner_id.phone', operator, value)])
    email = fields.Char(related="partner_id.email", store=True, readonly=False, tracking=True)
    address = fields.Char(compute="_compute_address", string="Address", store=True, readonly=False, tracking=True)
    animal_ids = fields.One2many('vet.animal', 'owner_id', string="Animals")

    @api.depends('partner_id.street', 'partner_id.street2', 'partner_id.city', 'partner_id.zip', 
                 'partner_id.state_id', 'partner_id.country_id')
    def _compute_address(self):
        for record in self:
            record.address = record.partner_id._display_address(without_company=True) if record.partner_id else False

    @api.constrains('contact_number')
    def _check_owner_contact_number(self):
        if self.env.context.get('skip_owner_validation'):
            return
        for record in self:
            partner = record.partner_id
            if not partner or partner.is_company or partner.user_ids:
                continue
            phone = record.contact_number
            if not phone:
                raise ValidationError(_("Contact number must be set for customers."))
            cleaned_phone = re.sub(r'\D', '', phone)
            if not re.fullmatch(r"\d{11}", cleaned_phone):
                raise ValidationError(_("Phone number must be exactly 11 digits."))
            dup_owner = self.search([("contact_number", "=", cleaned_phone), ("id", "!=", record.id)], limit=1)
            if dup_owner:
                raise ValidationError(_("Contact number must be unique among animal owners."))

    # **🚨 THIS IS YOUR MISSING METHOD!**
    @api.model_create_multi
    def create(self, vals_list):
        # **1. AUTO-CREATE PARTNER if no partner_id provided (VET MANAGEMENT)**
        for vals in vals_list:
            if not vals.get('partner_id'):
                # Create partner first
                partner_vals = {
                    'name': vals.get('name', 'Unknown Owner'),
                    'phone': vals.get('contact_number'),
                    'email': vals.get('email'),
                }
                
                # VALIDATE PHONE BEFORE CREATING
                cleaned_phone = re.sub(r'\D', '', partner_vals['phone'])
                if not re.fullmatch(r"\d{11}", cleaned_phone):
                    raise ValidationError(_("Phone number must be exactly 11 digits."))
                
                # Check uniqueness
                dup_owner = self.search([("contact_number", "=", cleaned_phone)], limit=1)
                if dup_owner:
                    raise ValidationError(_("Contact number must be unique among animal owners."))
                
                # Create partner
                partner = self.env['res.partner'].with_context(skip_owner_create=True).create(partner_vals)
                vals['partner_id'] = partner.id
        
        # **2. CREATE OWNERS**
        return super().create(vals_list)

class ResPartnerInherit(models.Model):
    _inherit = "res.partner"

    owner_id = fields.One2many("vet.animal.owner", "partner_id", string="Vet Owner")
    animal_ids = fields.One2many("vet.animal", "partner_id", string="Animals")
    dob = fields.Date(string="Date of Birth", tracking=True)
    age = fields.Char(string="Age", compute="_compute_age", store=True)

    @api.depends('dob')
    def _compute_age(self):
        for record in self:
            if record.dob:
                delta = relativedelta(fields.Date.today(), record.dob)
                years, months = delta.years, delta.months
                if years > 0:
                    record.age = f"{years} year{'s' if years > 1 else ''} {months} month{'s' if months > 1 else ''}" if months else f"{years} year{'s' if years > 1 else ''}"
                else:
                    record.age = f"{months} month{'s' if months > 1 else ''}"
            else:
                record.age = "0"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('is_company', False) and not vals.get('user_ids'):
                phone = vals.get('phone', '')
                cleaned_phone = re.sub(r'\D', '', phone)
                if not cleaned_phone:
                    raise ValidationError(_("Contact number must be set for customers."))
                if not re.fullmatch(r"\d{11}", cleaned_phone):
                    raise ValidationError(_("Phone number must be exactly 11 digits."))
                dup_owner = self.env['vet.animal.owner'].search([("contact_number", "=", cleaned_phone)], limit=1)
                if dup_owner:
                    raise ValidationError(_("Contact number must be unique among animal owners."))

        partners = super().create(vals_list)
        for partner in partners:
            if self.env.context.get("skip_owner_create"):
                continue
            if not partner.owner_id and not partner.is_company and not partner.user_ids:
                self.env['vet.animal.owner'].with_context(skip_owner_validation=True).create({"partner_id": partner.id})
        return partners

    def write(self, vals):
        # Pre-validate if phone is being updated
        if 'phone' in vals:
            for partner in self:
                if not partner.is_company and not partner.user_ids:
                    phone = vals.get('phone', partner.phone)
                    cleaned_phone = re.sub(r'\D', '', phone) if phone else ''
                    if not cleaned_phone:
                        raise ValidationError(_("Contact number must be set for customers."))
                    if not re.fullmatch(r"\d{11}", cleaned_phone):
                        raise ValidationError(_("Phone number must be exactly 11 digits."))
                    dup_owner = self.env['vet.animal.owner'].search([
                        ("contact_number", "=", cleaned_phone),
                        ("partner_id", "!=", partner.id),
                    ], limit=1)
                    if dup_owner:
                        raise ValidationError(_("Contact number must be unique among animal owners."))

        res = super().write(vals)
        
        # Create owners AFTER write is committed
        for partner in self:
            if self.env.context.get("skip_owner_create"):
                continue
            if not partner.owner_id and not partner.is_company and not partner.user_ids:
                self.env['vet.animal.owner'].with_context(skip_partner_create=True, skip_owner_validation=True).create({
                    "partner_id": partner.id,
                })
        return res

    @api.constrains('phone')
    def _check_phone(self):
        for record in self:
            # Skip validation for companies and backend users
            if record.is_company or record.user_ids:
                continue
    
            # Validate ALL individual partners
            phone = record.phone
            if not phone:
                raise ValidationError(_("Contact number must be set for customers."))
    
            cleaned_phone = re.sub(r'\D', '', phone)
            if not re.fullmatch(r"\d{11}", cleaned_phone):
                raise ValidationError(_("Phone number must be exactly 11 digits."))
    
            # Cross-check uniqueness across ALL individual partners
            dup_partner = self.search([
                ("phone", "ilike", cleaned_phone),
                ("id", "!=", record.id),
                ("is_company", "=", False),
                ("user_ids", "=", False),
            ], limit=1)
            if dup_partner:
                raise ValidationError(_("Contact number must be unique among customers."))
