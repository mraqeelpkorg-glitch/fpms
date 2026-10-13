// Copyright (c) 2026, Kodlyft and contributors
// For license information, please see license.txt

frappe.ui.form.on("Nozzle Reading", {
	nozzle(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.nozzle) return;
		frappe.call({
			method: "fpms.fuel_pump_management_system.doctype.shift_reconciliation.shift_reconciliation.get_nozzle_previous_closing",
			args: { nozzle: row.nozzle, exclude: frm.doc.name },
			callback(r) {
				if (r.message === null || r.message === undefined) {
					frappe.model.set_value(cdt, cdn, "previous_closing", 0);
					return;
				}
				frappe.model.set_value(cdt, cdn, "previous_closing", r.message);
				frappe.model.set_value(cdt, cdn, "opening_reading", r.message);
			},
		});
	},
});

frappe.ui.form.on("Shift Reconciliation", {
	// refresh(frm) {},
});
