from odoo import api, fields, models

class VetService(models.Model):
    _name = "vet.service"
    _description = "Vet Service / Test / Vaccine"
    _order = "name"

    name = fields.Char("Name", required=True)
    service_type = fields.Selection([
        ('service', 'Service'),
        ('vaccine', 'Vaccine'),
        ('test', 'Test')
    ], string="Type", required=True, default='service')
    price = fields.Float("Price", required=True, default=0.0)  # Added default
    product_id = fields.Many2one(
        "product.product",
        string="Linked Product",
        ondelete="set null"
    )
    description = fields.Text("Description")

    def _map_service_type_to_product_config(self, service_type):
        """Return product type and tracking based on service_type."""
        mapping = {
            'service': {'type': 'service', 'tracking': 'none'},
            'vaccine': {'type': 'consu', 'tracking': 'lot'},
            'test': {'type': 'consu', 'tracking': 'none'},
        }
        return mapping.get(service_type, {'type': 'service', 'tracking': 'none'})

    @api.model_create_multi
    def create(self, vals_list):
        if not isinstance(vals_list, list):
            vals_list = [vals_list]
        for vals in vals_list:
            # Ensure price has a default value
            if 'price' not in vals:
                vals['price'] = 0.0
            if not vals.get('product_id'):
                config = self._map_service_type_to_product_config(
                    vals.get('service_type', 'service')
                )
                product_vals = {
                    'name': vals.get('name', 'New Service'),
                    'list_price': vals.get('price', 0.0),
                    'type': config['type'],
                    'tracking': config['tracking'],
                }
                product = self.env['product.product'].create(product_vals)
                vals['product_id'] = product.id
        return super(VetService, self).create(vals_list)

    def write(self, vals):
        res = super().write(vals)
        for service in self:
            if service.product_id:
                product_vals = {}
                if 'price' in vals:
                    product_vals['list_price'] = vals['price']
                if 'name' in vals:
                    product_vals['name'] = vals['name']
                if 'service_type' in vals:
                    config = self._map_service_type_to_product_config(vals['service_type'])
                    product_vals['type'] = config['type']
                    product_vals['tracking'] = config['tracking']
                if product_vals:
                    service.product_id.write(product_vals)
        return res

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.price = self.product_id.list_price or 0.0
            if not self.name:
                self.name = self.product_id.name

    def action_add_product(self):
        """Open product creation form with defaults instead of auto-creating."""
        self.ensure_one()
        config = self._map_service_type_to_product_config(self.service_type or 'service')
        return {
            'name': 'Add Product',
            'type': 'ir.actions.act_window',
            'res_model': 'product.product',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_name': self.name,
                'default_list_price': self.price,
                'default_type': config['type'],
                'default_tracking': config['tracking'],
            }
        }
