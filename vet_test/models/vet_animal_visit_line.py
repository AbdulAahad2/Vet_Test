from odoo import api, fields, models
import logging

_logger = logging.getLogger(__name__)

# --------------------------------------------------------------
#  vet/animal/visit_line.py   (add / replace the whole class)
# --------------------------------------------------------------
class VetAnimalVisitLine(models.Model):
    _name = "vet.animal.visit.line"
    _description = "Animal Visit Line"

    # ------------------------------------------------------------------
    #  Existing fields (keep them)
    # ------------------------------------------------------------------
    service_id = fields.Many2one('vet.service', string='Service')
    product_id = fields.Many2one('product.product',
                                 related='service_id.product_id',
                                 store=True, readonly=True)
    service_type = fields.Selection(related='service_id.service_type',
                                    store=True, readonly=True)
    discount = fields.Float("Old Discount % (ignored)", default=0.0)
    visit_id = fields.Many2one('vet.animal.visit', string="Visit")
    quantity = fields.Float('Quantity', default=1.0)

    # ------------------------------------------------------------------
    #  LINE-LEVEL DISCOUNT (the only thing that changes the line)
    # ------------------------------------------------------------------
    line_discount = fields.Float(
        string="Discount % (line)",
        digits=(5, 2),
        default=0.0,
        help="Discount that only applies to this line."
    )

    # ------------------------------------------------------------------
    #  PRICE = list_price * (1 - line_discount/100)
    # ------------------------------------------------------------------
    price_unit = fields.Float(
        string='Unit Price',
        compute='_compute_price_unit',
        store=True,
        readonly=False,               # allow manual edit (will be overwritten by compute)
        digits='Product Price'
    )

    # ------------------------------------------------------------------
    #  SUBTOTAL = quantity * price_unit
    # ------------------------------------------------------------------
    subtotal = fields.Float(
        string='Subtotal',
        compute='_compute_subtotal',
        store=True,
        digits='Product Price'
    )

    # ------------------------------------------------------------------
    #  Keep the rest of the original fields (invoiced, delivered …)
    # ------------------------------------------------------------------
    invoiced = fields.Boolean(default=False, string="Invoiced")
    delivered = fields.Boolean(default=False, string="Delivered")

    # ------------------------------------------------------------------
    #  COMPUTED PRICE (list price → line discount)
    # ------------------------------------------------------------------
    @api.depends('service_id', 'service_id.product_id.lst_price',
                 'line_discount', 'quantity')
    def _compute_price_unit(self):
        for line in self:
            if not line.service_id or not line.service_id.product_id:
                line.price_unit = 0.0
                continue

            list_price = line.service_id.product_id.lst_price
            disc = line.line_discount or 0.0
            line.price_unit = list_price * (1 - disc / 100)

    # ------------------------------------------------------------------
    #  SUBTOTAL
    # ------------------------------------------------------------------
    @api.depends('quantity', 'price_unit')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.quantity * line.price_unit

    @api.onchange('price_unit')
    def _onchange_price_unit(self):
        if (self.service_id and
                self.service_id.service_type == 'vaccine'):
            # vaccines always keep list price (no manual edit)
            self.price_unit = self.service_id.product_id.lst_price
