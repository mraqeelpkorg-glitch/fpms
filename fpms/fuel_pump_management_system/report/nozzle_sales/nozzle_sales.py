# Copyright (c) 2026, Kodlyft and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt, get_first_day, get_last_day, getdate, nowdate


def execute(filters=None):
	filters = frappe._dict(filters or {})
	set_default_dates(filters)
	by_nozzle = filters.get("group_by") == "Nozzle"
	data = get_data(filters, by_nozzle)
	return get_columns(by_nozzle), data, None, get_chart(data, by_nozzle)


def set_default_dates(filters):
	# the dashboard chart and number cards call this without filters: default to this month
	if not filters.get("from_date"):
		filters.from_date = get_first_day(nowdate())
	if not filters.get("to_date"):
		filters.to_date = get_last_day(nowdate())
	if getdate(filters.from_date) > getdate(filters.to_date):
		frappe.throw(_("From Date cannot be after To Date"))


def get_columns(by_nozzle):
	nozzle = {"label": _("Nozzle"), "fieldname": "nozzle", "fieldtype": "Link", "options": "Nozzle", "width": 130}
	item = {"label": _("Fuel"), "fieldname": "item", "fieldtype": "Link", "options": "Item", "width": 130}
	litres = {"label": _("Sale (L)"), "fieldname": "sale_litres", "fieldtype": "Float", "precision": 3, "width": 110}
	amount = {"label": _("Sale Amount"), "fieldname": "sale_amount", "fieldtype": "Currency", "width": 130}
	if by_nozzle:
		return [
			nozzle,
			item,
			{"label": _("Shifts"), "fieldname": "shifts", "fieldtype": "Int", "width": 70},
			{"label": _("Testing (L)"), "fieldname": "testing_litres", "fieldtype": "Float", "precision": 3, "width": 100},
			litres,
			amount,
		]
	return [
		{"label": _("Date"), "fieldname": "shift_date", "fieldtype": "Date", "width": 100},
		{"label": _("Shift"), "fieldname": "shift", "fieldtype": "Link", "options": "Shift Reconciliation", "width": 150},
		{"label": _("Shift Type"), "fieldname": "shift_type", "fieldtype": "Link", "options": "Shift Type", "width": 100},
		nozzle,
		item,
		{"label": _("Opening"), "fieldname": "opening_reading", "fieldtype": "Float", "precision": 3, "width": 110},
		{"label": _("Closing"), "fieldname": "closing_reading", "fieldtype": "Float", "precision": 3, "width": 110},
		{"label": _("Testing (L)"), "fieldname": "testing_litres", "fieldtype": "Float", "precision": 3, "width": 100},
		litres,
		{"label": _("Rate"), "fieldname": "rate", "fieldtype": "Currency", "width": 90},
		amount,
	]


def get_data(filters, by_nozzle):
	conditions = ["sr.docstatus = 1", "sr.shift_date between %(from_date)s and %(to_date)s"]
	if filters.get("nozzle"):
		conditions.append("nr.nozzle = %(nozzle)s")
	if filters.get("item"):
		conditions.append("nr.item = %(item)s")
	if filters.get("shift_type"):
		conditions.append("sr.shift_type = %(shift_type)s")
	where = " and ".join(conditions)

	if by_nozzle:
		query = f"""
			select nr.nozzle, max(nr.item) as item, count(distinct sr.name) as shifts,
				sum(nr.testing_litres) as testing_litres, sum(nr.sale_litres) as sale_litres,
				sum(nr.sale_amount) as sale_amount
			from `tabNozzle Reading` nr
			join `tabShift Reconciliation` sr
				on nr.parent = sr.name and nr.parenttype = 'Shift Reconciliation'
			where {where}
			group by nr.nozzle
			order by nr.nozzle
		"""
	else:
		query = f"""
			select sr.shift_date, sr.name as shift, sr.shift_type, nr.nozzle, nr.item,
				nr.opening_reading, nr.closing_reading, nr.testing_litres, nr.sale_litres,
				nr.rate, nr.sale_amount
			from `tabNozzle Reading` nr
			join `tabShift Reconciliation` sr
				on nr.parent = sr.name and nr.parenttype = 'Shift Reconciliation'
			where {where}
			order by sr.shift_date desc, sr.shift_start_time desc, sr.name desc, nr.idx
		"""
	return frappe.db.sql(query, filters, as_dict=True)


def get_chart(data, by_nozzle):
	totals = {}
	for row in data:
		totals[row.nozzle] = totals.get(row.nozzle, 0) + flt(row.sale_litres)
	if not totals:
		return None
	return {
		"data": {
			"labels": list(totals),
			"datasets": [{"name": _("Sale (L)"), "values": [flt(v, 3) for v in totals.values()]}],
		},
		"type": "bar",
	}
