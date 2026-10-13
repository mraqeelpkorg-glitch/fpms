# Copyright (c) 2026, Kodlyft and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class NozzleReading(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		closing_reading: DF.Float
		item: DF.Link | None
		nozzle: DF.Link
		opening_override_reason: DF.SmallText | None
		opening_reading: DF.Float
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		previous_closing: DF.Float
		rate: DF.Currency
		sale_amount: DF.Currency
		sale_litres: DF.Float
		testing_litres: DF.Float
	# end: auto-generated types

	pass
