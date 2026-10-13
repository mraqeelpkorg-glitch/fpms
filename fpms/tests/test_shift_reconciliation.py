# Copyright (c) 2026, Kodlyft and contributors
# See license.txt

import itertools
import unittest

import frappe
from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
from frappe.tests import IntegrationTestCase
from frappe.utils import flt, nowdate

ITEM = "FPMS-TEST-PETROL"
RATE = 100  # per litre; a 100 L shift sells 10,000
_counter = itertools.count(1)


class TestShiftReconciliation(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.company = frappe.db.get_value("Company", {}, "name")
		if not cls.company:
			raise unittest.SkipTest("No Company on this site; finish the ERPNext setup wizard first.")
		cls.abbr = frappe.get_cached_value("Company", cls.company, "abbr")

		cls.warehouse = cls._make_warehouse()
		cls._make_item()
		cls.price_list = cls._make_price()
		cls.customer = cls._make_customer()
		cls.cash_account = cls._make_cash_mode()
		cls.shortage_account = cls._make_account("FPMS Test Shortage", "Indirect Expenses", "Expense")
		cls.excess_account = cls._make_account("FPMS Test Excess", "Indirect Income", "Income")
		cls.tank = cls._make_tank()
		make_stock_entry(
			item_code=ITEM, qty=5000, to_warehouse=cls.warehouse, company=cls.company, rate=80, basic_rate=80
		)
		cls._make_user()

	def setUp(self):
		frappe.set_user("Administrator")
		self._settings(
			default_company=self.company,
			default_customer=self.customer,
			default_price_list=self.price_list,
			shortage_account=self.shortage_account,
			excess_account=self.excess_account,
		)

	def tearDown(self):
		frappe.set_user("Administrator")

	# ------------------------------------------------------------------ fixtures

	@classmethod
	def _make_warehouse(cls):
		name = f"FPMS Test Tank - {cls.abbr}"
		if not frappe.db.exists("Warehouse", name):
			frappe.get_doc(
				{"doctype": "Warehouse", "warehouse_name": "FPMS Test Tank", "company": cls.company}
			).insert()
		return name

	@classmethod
	def _make_item(cls):
		if not frappe.db.exists("Item", ITEM):
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": ITEM,
					"item_name": ITEM,
					"item_group": "All Item Groups",
					"stock_uom": "Litre",
					"is_stock_item": 1,
					"fpms_is_fuel": 1,
				}
			).insert()

	@classmethod
	def _make_price(cls):
		currency = frappe.get_cached_value("Company", cls.company, "default_currency")
		price_list = frappe.db.get_value(
			"Price List", {"selling": 1, "enabled": 1, "currency": currency}, "name"
		)
		if not price_list:
			price_list = frappe.get_doc(
				{
					"doctype": "Price List",
					"price_list_name": "FPMS Test Selling",
					"currency": currency,
					"selling": 1,
					"enabled": 1,
				}
			).insert().name
		frappe.get_doc(
			{
				"doctype": "Item Price",
				"item_code": ITEM,
				"price_list": price_list,
				"price_list_rate": RATE,
				"selling": 1,
				"valid_from": "2000-01-01",
			}
		).insert()
		return price_list

	@classmethod
	def _make_customer(cls):
		name = "FPMS Test Walk-in"
		if not frappe.db.exists("Customer", name):
			frappe.get_doc(
				{
					"doctype": "Customer",
					"customer_name": name,
					"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
					"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"),
				}
			).insert()
		return name

	@classmethod
	def _make_cash_mode(cls):
		account = frappe.db.get_value(
			"Account", {"company": cls.company, "account_type": "Cash", "is_group": 0}, "name"
		)
		if not frappe.db.exists("Mode of Payment", "Cash"):
			frappe.get_doc({"doctype": "Mode of Payment", "mode_of_payment": "Cash", "type": "Cash"}).insert()
		mop = frappe.get_doc("Mode of Payment", "Cash")
		if not any(r.company == cls.company and r.default_account for r in mop.accounts):
			mop.append("accounts", {"company": cls.company, "default_account": account})
			mop.save()
		return frappe.db.get_value(
			"Mode of Payment Account", {"parent": "Cash", "company": cls.company}, "default_account"
		)

	@classmethod
	def _make_account(cls, name, parent_name, root_type):
		full = f"{name} - {cls.abbr}"
		if frappe.db.exists("Account", full):
			return full
		parent = frappe.db.get_value(
			"Account", {"company": cls.company, "account_name": parent_name, "is_group": 1}, "name"
		) or frappe.db.get_value(
			"Account", {"company": cls.company, "root_type": root_type, "is_group": 1}, "name"
		)
		frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": name,
				"company": cls.company,
				"parent_account": parent,
				"root_type": root_type,
			}
		).insert()
		return full

	@classmethod
	def _make_tank(cls):
		return frappe.get_doc(
			{
				"doctype": "Tank",
				"tank_name": "FPMS Test Tank",
				"warehouse": cls.warehouse,
				"item": ITEM,
				"company": cls.company,
			}
		).insert().name

	@classmethod
	def _make_user(cls):
		cls.cashier = "fpms.cashier.test@example.com"
		if not frappe.db.exists("User", cls.cashier):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": cls.cashier,
					"first_name": "FPMS Cashier",
					"send_welcome_email": 0,
					"roles": [{"role": "FPMS Cashier"}],
				}
			).insert()

	def _nozzle(self):
		n = next(_counter)
		return frappe.get_doc(
			{
				"doctype": "Nozzle",
				"nozzle_id": f"FPMS-TEST-N{n}-{frappe.generate_hash(length=4)}",
				"nozzle_name": f"Test Nozzle {n}",
				"tank": self.tank,
				"item": ITEM,
			}
		).insert().name

	def _settings(self, **values):
		for field, value in values.items():
			frappe.db.set_single_value("Fuel Pump Settings", field, value)

	def _shift(self, nozzle, opening=1000, closing=1100, payments=None, reason=None):
		row = {"nozzle": nozzle, "opening_reading": opening, "closing_reading": closing}
		if reason:
			row["opening_override_reason"] = reason
		return frappe.get_doc(
			{
				"doctype": "Shift Reconciliation",
				"shift_date": nowdate(),
				"reading_details": [row],
				"payment_details": [{"mode_of_payment": "Cash", "amount": a} for a in (payments or [])],
			}
		)

	def _submit(self, *args, **kwargs):
		doc = self._shift(*args, **kwargs)
		doc.insert()
		doc.submit()
		return doc

	def _linked(self, doctype, shift):
		return frappe.get_all(doctype, filters={"fpms_shift": shift, "docstatus": 1}, pluck="name")

	def _outstanding(self, invoice):
		return flt(frappe.db.get_value("Sales Invoice", invoice, "outstanding_amount"), 2)

	# ------------------------------------------------------------------ (b) payment entries

	def test_cash_collected_posts_payment_entry(self):
		shift = self._submit(self._nozzle(), payments=[10000])
		self.assertEqual(shift.variance_status, "Balanced")
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", shift.sales_invoice, "grand_total")), 10000)

		entries = self._linked("Payment Entry", shift.name)
		self.assertEqual(len(entries), 1)
		pe = frappe.get_doc("Payment Entry", entries[0])
		self.assertEqual(pe.paid_to, self.cash_account)
		self.assertEqual(flt(pe.paid_amount), 10000)
		self.assertEqual(pe.references[0].reference_name, shift.sales_invoice)
		self.assertEqual(self._outstanding(shift.sales_invoice), 0)

	def test_each_payment_row_gets_its_own_payment_entry(self):
		shift = self._submit(self._nozzle(), payments=[6000, 4000])
		entries = [frappe.get_doc("Payment Entry", n) for n in self._linked("Payment Entry", shift.name)]
		self.assertEqual(sorted(flt(e.paid_amount) for e in entries), [4000, 6000])
		self.assertEqual(self._outstanding(shift.sales_invoice), 0)

	def test_cancel_reverses_payment_entry_and_invoice(self):
		shift = self._submit(self._nozzle(), payments=[10000])
		invoice = shift.sales_invoice
		shift.cancel()
		self.assertEqual(self._linked("Payment Entry", shift.name), [])
		self.assertEqual(frappe.db.get_value("Sales Invoice", invoice, "docstatus"), 2)

	# ------------------------------------------------------------------ (c) shortage / excess

	def test_shortage_posts_journal_entry_and_clears_invoice(self):
		shift = self._submit(self._nozzle(), payments=[9000])
		self.assertEqual(shift.variance_status, "Shortage")

		entries = self._linked("Journal Entry", shift.name)
		self.assertEqual(len(entries), 1)
		je = frappe.get_doc("Journal Entry", entries[0])
		debit = next(r for r in je.accounts if r.account == self.shortage_account)
		self.assertEqual(flt(debit.debit_in_account_currency), 1000)
		self.assertEqual(flt(je.total_debit), flt(je.total_credit))
		self.assertEqual(self._outstanding(shift.sales_invoice), 0)

	def test_excess_posts_journal_entry(self):
		shift = self._submit(self._nozzle(), payments=[10500])
		self.assertEqual(shift.variance_status, "Excess")

		je = frappe.get_doc("Journal Entry", self._linked("Journal Entry", shift.name)[0])
		credit = next(r for r in je.accounts if r.account == self.excess_account)
		self.assertEqual(flt(credit.credit_in_account_currency), 500)
		cash = next(r for r in je.accounts if r.account == self.cash_account)
		self.assertEqual(flt(cash.debit_in_account_currency), 500)
		# the invoice itself is settled by the Payment Entry for exactly what was billed
		self.assertEqual(self._outstanding(shift.sales_invoice), 0)

	def test_balanced_shift_posts_no_journal_entry(self):
		shift = self._submit(self._nozzle(), payments=[10000])
		self.assertEqual(self._linked("Journal Entry", shift.name), [])

	def test_shortage_blocked_without_shortage_account(self):
		self._settings(shortage_account=None)
		doc = self._shift(self._nozzle(), payments=[9000])
		doc.insert()
		with self.assertRaises(frappe.ValidationError):
			doc.submit()
		self.assertEqual(frappe.db.get_value("Shift Reconciliation", doc.name, "docstatus"), 0)

	def test_excess_blocked_without_excess_account(self):
		self._settings(excess_account=None)
		doc = self._shift(self._nozzle(), payments=[10500])
		doc.insert()
		with self.assertRaises(frappe.ValidationError):
			doc.submit()
		self.assertEqual(frappe.db.get_value("Shift Reconciliation", doc.name, "docstatus"), 0)

	# ------------------------------------------------------------------ (d) nozzle openings

	def test_opening_autofills_from_previous_closing(self):
		nozzle = self._nozzle()
		self._submit(nozzle, opening=1000, closing=1100, payments=[10000])

		nxt = self._shift(nozzle, opening=0, closing=1180)
		nxt.insert()
		row = nxt.reading_details[0]
		self.assertEqual(flt(row.opening_reading), 1100)
		self.assertEqual(flt(row.previous_closing), 1100)
		self.assertEqual(flt(row.sale_litres), 80)

	def test_first_reading_keeps_manual_opening(self):
		doc = self._shift(self._nozzle(), opening=2500, closing=2600)
		doc.insert()
		self.assertEqual(flt(doc.reading_details[0].opening_reading), 2500)

	def test_opening_mismatch_blocked_for_cashier(self):
		nozzle = self._nozzle()
		self._submit(nozzle, opening=1000, closing=1100, payments=[10000])

		frappe.set_user(self.cashier)
		doc = self._shift(nozzle, opening=1050, closing=1150)
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)

	def test_manager_override_requires_reason(self):
		nozzle = self._nozzle()
		self._submit(nozzle, opening=1000, closing=1100, payments=[10000])

		with self.assertRaises(frappe.ValidationError):
			self._shift(nozzle, opening=1050, closing=1150).insert()

		doc = self._shift(nozzle, opening=1050, closing=1150, reason="Totalizer replaced after repair")
		doc.insert()
		self.assertEqual(flt(doc.reading_details[0].opening_reading), 1050)
