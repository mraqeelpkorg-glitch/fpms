# Copyright (c) 2026, Kodlyft and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
	filters = frappe._dict(filters or {})
	data = get_data(filters)
	return get_columns(), data, None, get_chart(data)


def get_columns():
	return [
		{"label": _("Tank"), "fieldname": "tank", "fieldtype": "Link", "options": "Tank", "width": 140},
		{"label": _("Fuel"), "fieldname": "item", "fieldtype": "Link", "options": "Item", "width": 130},
		{"label": _("Warehouse"), "fieldname": "warehouse", "fieldtype": "Link", "options": "Warehouse", "width": 180},
		{"label": _("Capacity (L)"), "fieldname": "capacity_litres", "fieldtype": "Float", "precision": 0, "width": 110},
		{"label": _("Stock (L)"), "fieldname": "stock_litres", "fieldtype": "Float", "precision": 0, "width": 110},
		{"label": _("Filled %"), "fieldname": "filled_pct", "fieldtype": "Percent", "width": 90},
	]


def get_data(filters):
	conditions = ["t.status = 'Active'"]
	if filters.get("item"):
		conditions.append("t.item = %(item)s")
	where = " and ".join(conditions)
	rows = frappe.db.sql(
		f"""
		select t.name as tank, t.item, t.warehouse, t.capacity_litres,
			ifnull(b.actual_qty, 0) as stock_litres
		from `tabTank` t
		left join `tabBin` b on b.warehouse = t.warehouse and b.item_code = t.item
		where {where}
		order by t.name
		""",
		filters,
		as_dict=True,
	)
	for row in rows:
		capacity = flt(row.capacity_litres)
		row.filled_pct = flt(row.stock_litres) / capacity * 100 if capacity else 0
	return rows


def get_chart(data):
	if not data:
		return None
	return {
		"data": {
			"labels": [r.tank for r in data],
			"datasets": [{"name": _("Stock (L)"), "values": [flt(r.stock_litres, 0) for r in data]}],
		},
		"type": "bar",
	}
