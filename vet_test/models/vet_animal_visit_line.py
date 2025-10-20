from odoo import api, fields, models
import logging

_logger = logging.getLogger(__name__)

class VetAnimalVisitLine(models.Model):
    _name = "vet.animal.visit.line"
    _description = "Animal Visit Line"

    service_id = fields.Many2one('vet.service', string='Service')
    product_id = fields.Many2one('product.product', related='service_id.product_id', store=True, readonly=True)
    service_type = fields.Selection(related='service_id.service_type', store=True, readonly=True)
    visit_id = fields.Many2one('vet.animal.visit', string="Visit")
    quantity = fields.Float('Quantity', default=1.0)
    price_unit = fields.Float('Unit Price', compute='_compute_price_unit', store=True)
    subtotal = fields.Float('Subtotal', compute='_compute_subtotal', store=True)
    line_type = fields.Selection([
        ('service', 'Service'),
        ('test', 'Test'),
        ('vaccine', 'Vaccine')
    ], required=True, default='service')
    invoiced = fields.Boolean(default=False, string="Invoiced")
    delivered = fields.Boolean(default=False, string="Delivered")
    discount = fields.Float("Discount (%)", default=0.0)

    @api.depends('service_id')
    def _compute_price_unit(self):
        for line in self:
            if line.service_id and line.service_id.product_id:
                line.price_unit = line.service_id.product_id.list_price
            elif line.service_id:
                line.price_unit = getattr(line.service_id, 'price', 0.0)
            else:
                line.price_unit = 0.0

    @api.depends('quantity', 'price_unit')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.quantity * line.price_unit if line.product_id else 0.0
            _logger.debug("Visit line %s: quantity=%s, price_unit=%s, subtotal=%s",
                          line.id, line.quantity, line.price_unit, line.subtotal)
