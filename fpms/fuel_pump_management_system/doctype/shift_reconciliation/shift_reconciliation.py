# Copyright (c) 2026, Kodlyft and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

OVERRIDE_ROLES = {"FPMS Manager", "System Manager"}
EPS = 0.005

from fpms.events.pricing import get_effective_price


class ShiftReconciliation(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from fpms.fuel_pump_management_system.doctype.fuel_credit_sale.fuel_credit_sale import FuelCreditSale
		from fpms.fuel_pump_management_system.doctype.nozzle_reading.nozzle_reading import NozzleReading
		from fpms.fuel_pump_management_system.doctype.shift_payment.shift_payment import ShiftPayment

		amended_from: DF.Link | None
		credit_sales: DF.Table[FuelCreditSale]
		employee: DF.Link | None
		naming_series: DF.Literal["FPMS-SHIFT-.YYYY.-"]
		payment_details: DF.Table[ShiftPayment]
		pos_profile: DF.Link | None
		reading_details: DF.Table[NozzleReading]
		sales_invoice: DF.Link | None
		shift_date: DF.Date
		shift_end_time: DF.Time | None
		shift_start_time: DF.Time | None
		shift_type: DF.Link | None
		status: DF.Literal["Draft", "Submitted", "Cancelled"]
		stock_entry: DF.Link | None
		total_collected: DF.Currency
		total_credit_sales: DF.Currency
		total_fuel_litres: DF.Float
		total_fuel_sales: DF.Currency
		variance_amount: DF.Currency
		variance_status: DF.Literal["Balanced", "Shortage", "Excess"]
	# end: auto-generated types

	def validate(self):
		self.set_opening_readings()
		self.calculate_readings()
		self.calculate_credit_sales()
		self.calculate_totals()
		self.set_variance()
		self.set_status()

	def before_submit(self):
		self.validate_posting_prerequisites()

	def on_submit(self):
		self.create_credit_invoices()
		self.create_cash_sales_invoice()
		self.create_payment_entries()
		self.post_variance_entry()
		self.db_set("status", self._status_value())

	def on_cancel(self):
		self.cancel_linked_documents()
		self.db_set("status", self._status_value())

	def _price_list(self):
		if self.pos_profile:
			pl = frappe.db.get_value("POS Profile", self.pos_profile, "selling_price_list")
			if pl:
				return pl
		return frappe.db.get_single_value("Fuel Pump Settings", "default_price_list")

	def _rate_for(self, item, price_list):
		if not item or not price_list:
			return 0.0
		return get_effective_price(item, price_list, self.shift_date)

	def calculate_readings(self):
		"""Compute per-nozzle sale litres and value at the effective-dated price."""
		price_list = self._price_list()
		for row in self.reading_details:
			if not row.item and row.nozzle:
				row.item = frappe.db.get_value("Nozzle", row.nozzle, "item")

			row.sale_litres = flt(row.closing_reading) - flt(row.opening_reading) - flt(row.testing_litres)
			if row.sale_litres < 0:
				frappe.throw(
					_(
						"Row #{0}: closing reading cannot be less than opening plus testing for nozzle {1}."
					).format(row.idx, row.nozzle)
				)

			if not row.rate and row.item and price_list:
				row.rate = self._rate_for(row.item, price_list)
			row.sale_amount = flt(row.sale_litres) * flt(row.rate)

	def calculate_credit_sales(self):
		"""Value each on-account fuel sale at the effective-dated price."""
		price_list = self._price_list()
		for row in self.credit_sales:
			if not row.item and row.nozzle:
				row.item = frappe.db.get_value("Nozzle", row.nozzle, "item")
			if row.fuel_card and not row.customer:
				row.customer = frappe.db.get_value("Fuel Card", row.fuel_card, "customer")

			if not row.rate and row.item and price_list:
				row.rate = self._rate_for(row.item, price_list)
			row.amount = flt(row.litres) * flt(row.rate)

	def calculate_totals(self):
		self.total_fuel_litres = sum(flt(r.sale_litres) for r in self.reading_details)
		self.total_fuel_sales = sum(flt(r.sale_amount) for r in self.reading_details)
		self.total_collected = sum(flt(p.amount) for p in self.payment_details)
		self.total_credit_sales = sum(flt(r.amount) for r in self.credit_sales)

	def set_variance(self):
		# Everything dispensed should be either collected (cash/card) or billed on credit.
		accounted = flt(self.total_collected) + flt(self.total_credit_sales)
		self.variance_amount = accounted - flt(self.total_fuel_sales)
		if abs(self.variance_amount) < 0.005:
			self.variance_status = "Balanced"
		elif self.variance_amount < 0:
			self.variance_status = "Shortage"
		else:
			self.variance_status = "Excess"

	def set_status(self):
		self.status = self._status_value()

	def _status_value(self):
		return {0: "Draft", 1: "Submitted", 2: "Cancelled"}[self.docstatus]


	# ------------------------------------------------------------ nozzle openings

	def set_opening_readings(self):
		"""Opening = the nozzle's last submitted closing. Only a manager may override, with a reason."""
		for row in self.reading_details:
			if not row.nozzle:
				continue

			previous = get_previous_closing(row.nozzle, exclude=self.name)
			old_previous = flt(row.get("previous_closing"))
			row.previous_closing = flt(previous) if previous is not None else 0

			if previous is None:
				continue  # first reading ever recorded for this nozzle: opening is entered by hand

			opening = flt(row.opening_reading)
			if not opening or abs(opening - old_previous) < 0.0005:
				row.opening_reading = previous  # untouched by the user: keep following the chain
				continue

			if abs(opening - flt(previous)) < 0.0005:
				continue

			if not (OVERRIDE_ROLES & set(frappe.get_roles())):
				frappe.throw(
					_("Row #{0}: opening reading {1} for nozzle {2} must equal the previous closing {3}.").format(
						row.idx, opening, row.nozzle, previous
					)
				)
			if not (row.get("opening_override_reason") or "").strip():
				frappe.throw(
					_("Row #{0}: enter an Opening Override Reason to use {1} instead of the previous closing {2}.").format(
						row.idx, opening, previous
					)
				)

	# ------------------------------------------------------------ settlement setup

	def _company(self):
		company = None
		if self.pos_profile:
			company = frappe.db.get_value("POS Profile", self.pos_profile, "company")
		return (
			frappe.db.get_single_value("Fuel Pump Settings", "default_company")
			or company
			or frappe.defaults.get_global_default("company")
		)

	def validate_posting_prerequisites(self):
		"""Refuse to submit when the money cannot be posted."""
		settings = frappe.get_doc("Fuel Pump Settings")
		if self.variance_status == "Shortage" and not settings.shortage_account:
			frappe.throw(_("Set the Shortage Account in Fuel Pump Settings before submitting a shift with a shortage."))
		if self.variance_status == "Excess" and not settings.excess_account:
			frappe.throw(_("Set the Excess Account in Fuel Pump Settings before submitting a shift with an excess."))

		company = self._company()
		for row in self.payment_details:
			if flt(row.amount) <= 0:
				continue
			if not row.mode_of_payment:
				frappe.throw(_("Payment row #{0} has no Mode of Payment.").format(row.idx))
			_mode_account(row.mode_of_payment, company)

	# ------------------------------------------------------------------ postings

	def _resolve_customer(self):
		if self.pos_profile:
			cust = frappe.db.get_value("POS Profile", self.pos_profile, "customer")
			if cust:
				return cust
		return frappe.db.get_single_value("Fuel Pump Settings", "default_customer")

	def _new_fuel_invoice(self, customer, update_stock=1):
		invoice = frappe.new_doc("Sales Invoice")
		invoice.customer = customer
		invoice.company = self._company()
		invoice.currency = frappe.get_cached_value("Company", invoice.company, "default_currency")
		price_list = self._price_list()
		if price_list:
			invoice.selling_price_list = price_list
		invoice.posting_date = self.shift_date
		invoice.set_posting_time = 1
		invoice.update_stock = update_stock
		invoice.fpms_shift = self.name
		invoice.flags.ignore_permissions = True
		return invoice

	def create_credit_invoices(self):
		"""Bill each credit customer a Sales Invoice on account (posts to their receivable)."""
		if not self.credit_sales:
			return

		by_customer = {}
		for row in self.credit_sales:
			if not row.customer:
				frappe.throw(_("Credit sale row #{0} has no customer.").format(row.idx))
			by_customer.setdefault(row.customer, []).append(row)

		for customer, rows in by_customer.items():
			lines = _group_fuel_lines(rows, litres_field="litres")
			if not lines:
				continue

			invoice = self._new_fuel_invoice(customer)
			invoice.remarks = _("Credit fuel sales for shift {0}").format(self.name)
			_append_fuel_lines(invoice, lines)
			invoice.set_missing_values()
			invoice.insert()
			invoice.submit()

			for row in rows:
				row.db_set("sales_invoice", invoice.name)

	def create_cash_sales_invoice(self):
		"""Invoice the walk-in customer for the cash portion (throughput minus credit litres).

		Fuel is a non-taxable supply, so no tax template is applied. ``update_stock`` on each
		fuel invoice relieves wet-stock from the tank warehouse; the cash and credit invoices
		together relieve exactly the shift's throughput.
		"""
		if self.sales_invoice:
			return

		cash_lines = self._cash_fuel_lines()
		if not cash_lines:
			return

		customer = self._resolve_customer()
		if not customer:
			frappe.msgprint(
				_(
					"No default customer set on the POS Profile or Fuel Pump Settings. "
					"Skipping the cash Sales Invoice. Cash-sold wet-stock was not relieved."
				),
				alert=True,
			)
			return

		invoice = self._new_fuel_invoice(customer)
		invoice.remarks = _("Cash fuel sales for shift {0}").format(self.name)
		_append_fuel_lines(invoice, cash_lines)
		invoice.set_missing_values()
		invoice.insert()
		invoice.submit()
		self.db_set("sales_invoice", invoice.name)

	def _cash_fuel_lines(self):
		"""Throughput per (item, warehouse) minus credit litres = the cash-sold portion."""
		throughput = _group_fuel_lines(self.reading_details, litres_field="sale_litres")
		credit = _group_fuel_lines(self.credit_sales, litres_field="litres")

		cash = {}
		for key, data in throughput.items():
			qty = flt(data["qty"]) - flt(credit.get(key, {}).get("qty", 0))
			if qty > 0.0005:
				cash[key] = {"qty": qty, "rate": data["rate"]}
		return cash


	def create_payment_entries(self):
		"""Post the cash collected: one Payment Entry per payment row against the cash invoice.

		Whatever the invoice cannot absorb (collected more than billed) is kept in ``_excess``
		for the variance Journal Entry.
		"""
		self._excess = []
		rows = [p for p in self.payment_details if flt(p.amount) > 0]
		if not rows:
			return

		invoice = frappe.get_doc("Sales Invoice", self.sales_invoice) if self.sales_invoice else None
		company = invoice.company if invoice else self._company()
		remaining = flt(invoice.outstanding_amount, 2) if invoice else 0.0

		for row in rows:
			account = _mode_account(row.mode_of_payment, company)
			amount = flt(row.amount, 2)
			allocated = min(amount, remaining) if invoice else 0.0
			if allocated > EPS:
				self._make_payment_entry(invoice, row, account, allocated)
				remaining = flt(remaining - allocated, 2)
			extra = flt(amount - allocated, 2)
			if extra > EPS:
				self._excess.append((account, extra))

	def _make_payment_entry(self, invoice, row, account, amount):
		pe = frappe.new_doc("Payment Entry")
		pe.payment_type = "Receive"
		pe.company = invoice.company
		pe.posting_date = self.shift_date
		pe.mode_of_payment = row.mode_of_payment
		pe.party_type = "Customer"
		pe.party = invoice.customer
		pe.paid_from = invoice.debit_to
		pe.paid_to = account
		pe.paid_from_account_currency = invoice.party_account_currency
		pe.paid_to_account_currency = frappe.get_cached_value("Account", account, "account_currency")
		pe.paid_amount = amount
		pe.received_amount = amount
		pe.source_exchange_rate = 1
		pe.target_exchange_rate = 1
		pe.reference_no = row.reference or self.name
		pe.reference_date = self.shift_date
		pe.remarks = _("Cash collected for shift {0}").format(self.name)
		pe.fpms_shift = self.name
		pe.append(
			"references",
			{"reference_doctype": "Sales Invoice", "reference_name": invoice.name, "allocated_amount": amount},
		)
		pe.flags.ignore_permissions = True
		pe.insert()
		pe.submit()
		return pe

	def post_variance_entry(self):
		"""Book a shortage or excess to its Fuel Pump Settings account via a Journal Entry."""
		if self.variance_status == "Balanced":
			return

		settings = frappe.get_doc("Fuel Pump Settings")
		invoice = frappe.get_doc("Sales Invoice", self.sales_invoice) if self.sales_invoice else None
		company = invoice.company if invoice else self._company()
		lines = []

		if self.variance_status == "Shortage":
			outstanding = flt(frappe.db.get_value("Sales Invoice", self.sales_invoice, "outstanding_amount"), 2) if invoice else 0.0
			amount = min(outstanding, abs(flt(self.variance_amount, 2)))
			if amount > EPS:
				shortage = {"account": settings.shortage_account, "debit_in_account_currency": amount}
				if self.employee and _is_party_account(settings.shortage_account):
					shortage.update({"party_type": "Employee", "party": self.employee})
				lines.append(shortage)
				lines.append(
					{
						"account": invoice.debit_to,
						"party_type": "Customer",
						"party": invoice.customer,
						"credit_in_account_currency": amount,
						"reference_type": "Sales Invoice",
						"reference_name": invoice.name,
					}
				)
		else:
			for account, extra in getattr(self, "_excess", []):
				lines.append({"account": account, "debit_in_account_currency": extra})
				lines.append({"account": settings.excess_account, "credit_in_account_currency": extra})

		if not lines:
			return

		remark = _("{0} for shift {1}").format(_(self.variance_status), self.name)
		if self.employee:
			remark += _(" (employee {0})").format(self.employee)

		je = frappe.new_doc("Journal Entry")
		je.voucher_type = "Journal Entry"
		je.company = company
		je.posting_date = self.shift_date
		je.user_remark = remark
		je.fpms_shift = self.name
		for line in lines:
			je.append("accounts", line)
		je.flags.ignore_permissions = True
		je.insert()
		je.submit()

	def cancel_linked_documents(self):
		"""Cancel everything this shift posted: variance JE, payments, then the invoices."""
		for doctype in ("Journal Entry", "Payment Entry"):
			for name in frappe.get_all(doctype, filters={"fpms_shift": self.name, "docstatus": 1}, pluck="name"):
				doc = frappe.get_doc(doctype, name)
				doc.flags.ignore_permissions = True
				doc.cancel()

		invoices = frappe.get_all(
			"Sales Invoice",
			filters={"fpms_shift": self.name, "docstatus": 1},
			pluck="name",
		)
		for name in invoices:
			inv = frappe.get_doc("Sales Invoice", name)
			inv.flags.ignore_permissions = True
			inv.cancel()


def resolve_warehouse(item, nozzle=None):
	"""Resolve the tank warehouse for a fuel line: nozzle's tank, else any tank for the item."""
	tank = None
	if nozzle:
		tank = frappe.db.get_value("Nozzle", nozzle, "tank")
	if not tank and item:
		tank = frappe.db.get_value("Tank", {"item": item}, "name")
	return frappe.db.get_value("Tank", tank, "warehouse") if tank else None


def _group_fuel_lines(rows, litres_field):
	"""Group rows by (item, tank warehouse), summing litres and keeping the rate."""
	lines = {}
	for row in rows:
		litres = flt(row.get(litres_field))
		if not row.item or litres <= 0:
			continue
		warehouse = resolve_warehouse(row.item, row.get("nozzle"))
		key = (row.item, warehouse)
		bucket = lines.setdefault(key, {"qty": 0.0, "rate": flt(row.rate)})
		bucket["qty"] += litres
	return lines


def _append_fuel_lines(invoice, lines):
	for (item_code, warehouse), data in lines.items():
		invoice.append(
			"items",
			{
				"item_code": item_code,
				"qty": data["qty"],
				"rate": data["rate"],
				"warehouse": warehouse,
			},
		)


def get_previous_closing(nozzle, exclude=None):
	"""Closing reading of the nozzle's most recent submitted Shift Reconciliation, or None."""
	rows = frappe.db.sql(
		"""
		SELECT nr.closing_reading
		FROM `tabNozzle Reading` nr
		JOIN `tabShift Reconciliation` sr ON sr.name = nr.parent AND nr.parenttype = 'Shift Reconciliation'
		WHERE nr.nozzle = %(nozzle)s AND sr.docstatus = 1 AND sr.name != %(exclude)s
		ORDER BY sr.shift_date DESC, sr.shift_start_time DESC, sr.creation DESC
		LIMIT 1
		""",
		{"nozzle": nozzle, "exclude": exclude or ""},
	)
	return flt(rows[0][0]) if rows else None


@frappe.whitelist()
def get_nozzle_previous_closing(nozzle, exclude=None):
	frappe.has_permission("Shift Reconciliation", "read", throw=True)
	return get_previous_closing(nozzle, exclude)


def _mode_account(mode_of_payment, company):
	account = frappe.db.get_value(
		"Mode of Payment Account", {"parent": mode_of_payment, "company": company}, "default_account"
	)
	if not account:
		frappe.throw(
			_("Set a default account for Mode of Payment {0} and company {1}.").format(mode_of_payment, company)
		)
	return account


def _is_party_account(account):
	return frappe.db.get_value("Account", account, "account_type") in ("Receivable", "Payable")
