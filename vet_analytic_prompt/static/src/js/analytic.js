/** @odoo-module **/

import { kanbanView } from "@web/views/kanban/kanban_view";
import { registry } from "@web/core/registry";

const { onMounted } = owl;

class AnalyticKanbanController extends kanbanView.Controller {
    setup() {
        super.setup();
        onMounted(() => {
            // Add click handler to ALL cards
            document.addEventListener('click', this.onCardClick.bind(this));
        });
    }

    onCardClick(ev) {
        const card = ev.target.closest('.analytic-select-card');
        if (!card) return;

        ev.preventDefault();
        ev.stopPropagation();

        // Remove previous selection
        document.querySelectorAll('.analytic-select-card').forEach(c => 
            c.classList.remove('selected')
        );

        // Select this card
        card.classList.add('selected');

        // Get data
        const id = card.dataset.id;
        const name = card.dataset.name;

        // TOAST MESSAGE
        this.env.services.notification.add(
            `✅ SELECTED: ${name} (ID: ${id})`,
            { type: 'success', sticky: false }
        );

        // COPY ID
        navigator.clipboard.writeText(id);
    }
}

registry.category("views").add("analytic_kanban", {
    ...kanbanView,
    Controller: AnalyticKanbanController,
});
