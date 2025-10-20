from odoo import fields, models, api, _
from odoo.exceptions import ValidationError
import re
import logging
from dateutil.relativedelta import relativedelta

_logger = logging.getLogger(__name__)

class VetAnimal(models.Model):
    _name = "vet.animal"
    _description = "Animal"
    _rec_name = "microchip_no"
    _inherit = ['mail.thread', 'mail.activity.mixin']

    _sql_constraints = [
        ('microchip_unique', 'unique(microchip_no)', 'Animal ID be unique!')
    ]

    microchip_no = fields.Char(
        string="Animal ID",
        required=True,
        copy=False,
        readonly=True,
        index=True,
        default="New",
        tracking=True
    )
    name = fields.Char(string="Name", required=True, tracking=True)
    dob = fields.Date(string="Date of Birth", tracking=True)
    age = fields.Char(string="Age", compute="_compute_age", store=True)
    gender = fields.Selection([('male', 'Male'), ('female', 'Female')], string="Gender", tracking=True)
    species = fields.Selection([('dog', 'Dog'), ('cat', 'Cat'), ('other', 'Other')], string="Species", tracking=True)
    breed = fields.Char(string="Breed", tracking=True)
    owner_id = fields.Many2one('vet.animal.owner', string="Owner", tracking=True)
    contact_number = fields.Char(related='owner_id.contact_number', string="Owner Contact", store=True, readonly=True)
    image_1920 = fields.Image(string="Animal Image", max_width=1920, max_height=1920)
    active = fields.Boolean(string="Active", default=True)
    notes = fields.Text(string="Additional Notes")
    partner_id = fields.Many2one(
        'res.partner',
        string='Contact',
        related='owner_id.partner_id',
        store=True,
        index=True
    )
    attachment_count = fields.Integer(string="Attachment Count", compute="_compute_attachment_count")
    attachment_ids = fields.One2many(
        'ir.attachment', 
        'res_id', 
        string="Attachments",
        domain=[('res_model', '=', 'vet.animal')]
    )

    # 🔥 NEW! COMPUTE ATTACHMENT COUNT
    @api.depends('attachment_ids')
    def _compute_attachment_count(self):
        for record in self:
            record.attachment_count = len(record.attachment_ids)

    # 🔥 NEW! ACTION TO VIEW ATTACHMENTS
    def action_view_attachments(self):
        self.ensure_one()
        return {
            'name': _('Attachments'),
            'type': 'ir.actions.act_window',
            'res_model': 'ir.attachment',
            'view_mode': 'list,form',
            'domain': [('res_model', '=', 'vet.animal'), ('res_id', '=', self.id)],
            'context': "{'create': True}",
            'target': 'current',
        }

    @api.depends('dob')
    def _compute_age(self):
        for record in self:
            if record.dob:
                today = fields.Date.today()
                delta = relativedelta(today, record.dob)
                years = delta.years
                months = delta.months
                if years > 0:
                    if months > 0:
                        record.age = f"{years} year{'s' if years > 1 else ''} {months} month{'s' if months > 1 else ''}"
                    else:
                        record.age = f"{years} year{'s' if years > 1 else ''}"
                else:
                    record.age = f"{months} month{'s' if months > 1 else ''}"
            else:
                record.age = "0"

    @api.model_create_multi
    def create(self, vals_list):
        processed_vals = []
        for vals in vals_list:
            vals_copy = vals.copy()
            
            # **1. HANDLE PARTNER_ID → CREATE OWNER AUTOMATICALLY**
            partner_id = vals_copy.get("partner_id")
            if partner_id and not vals_copy.get("owner_id"):
                # Search existing owner
                owner = self.env["vet.animal.owner"].search([("partner_id", "=", partner_id)], limit=1)
                if not owner:
                    # **CREATE NEW OWNER!**
                    owner = self.env["vet.animal.owner"].with_context(skip_owner_validation=True).create({"partner_id": partner_id})
                vals_copy["owner_id"] = owner.id
            
            # **2. MANDATORY OWNER CHECK**
            if not vals_copy.get('owner_id'):
                raise ValidationError("Add an owner.")
            
            # **3. VALIDATE PHONE (11 digits + UNIQUE)**
            owner_id = vals_copy.get('owner_id')
            if owner_id:
                owner = self.env['vet.animal.owner'].browse(owner_id)
                if owner.partner_id and not owner.partner_id.is_company and not owner.partner_id.user_ids:
                    phone = owner.partner_id.phone
                    if not phone:
                        raise ValidationError(_("Contact number must be set for customers."))
                    cleaned_phone = re.sub(r'\D', '', phone)
                    if not re.fullmatch(r"\d{11}", cleaned_phone):
                        raise ValidationError(_("Phone number must be exactly 11 digits."))
                    dup_owner = self.env['vet.animal.owner'].search([
                        ("contact_number", "=", cleaned_phone),
                        ("id", "!=", owner.id),
                    ], limit=1)
                    if dup_owner:
                        raise ValidationError(_("Contact number must be unique among animal owners."))
            
            # **4. HANDLE MICROCHIP**
            microchip_no = vals_copy.get('microchip_no')
            _logger.info(f"Creating animal with Animal ID: {microchip_no}")
            if not microchip_no or microchip_no == "New":
                vals_copy['microchip_no'] = self.env['ir.sequence'].next_by_code('vet.animal.microchip') or 'HT000000'
                _logger.info(f"Generated Animal ID: {vals_copy['microchip_no']}")
            else:
                if self.search([('microchip_no', '=', microchip_no)]):
                    _logger.error(f"Duplicate Animal ID detected: {microchip_no}")
                    raise ValidationError(f"Animal ID '{microchip_no}' already exists!")
            
            processed_vals.append(vals_copy)
        
        return super(VetAnimal, self).create(processed_vals)

    def name_get(self):
        result = []
        for rec in self:
            display = "[%s] %s" % (rec.microchip_no or "", rec.name or "")
            if rec.owner_id:
                display = "%s - Owner: %s" % (display, rec.owner_id.name)
            result.append((rec.id, display))
        return result

    @api.model
    def name_search(self, name='', args=None, operator='ilike', limit=100):
        args = args or []
        domain = []
        name = (name or '').strip()
        if name.startswith('#'):
            chip = name[1:].strip()
            domain = [('microchip_no', '=', chip)]
        elif name.upper().startswith('HT'):
            domain = [('microchip_no', operator, name)]
        else:
            domain = [('name', operator, name)]
        records = self.search(domain + args, limit=limit)
        return records.name_get()

