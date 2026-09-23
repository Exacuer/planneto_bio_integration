# Copyright (c) 2026, Administrator and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class eSSLRawPunch(Document):
	def before_insert(self):
		self.link_employee()

	def validate(self):
		self.link_employee()

	def link_employee(self):
		"""Match attendance_device_id to Employee.attendance_device_id or Employee.name."""
		device_id = (self.attendance_device_id or "").strip()
		if not device_id:
			return

		if self.employee:
			self._set_employee_device_id(self.employee, device_id)
			return

		employee = frappe.db.get_value("Employee", {"attendance_device_id": device_id}, "name")
		if not employee and device_id.isdigit():
			employee = frappe.db.get_value(
				"Employee",
				{"attendance_device_id": str(int(device_id))},
				"name",
			)
		if not employee and frappe.db.exists("Employee", device_id):
			employee = device_id

		if employee:
			self.employee = employee
			self._set_employee_device_id(employee, device_id)

	@staticmethod
	def _set_employee_device_id(employee, device_id):
		current = frappe.db.get_value("Employee", employee, "attendance_device_id")
		if not current:
			frappe.db.set_value(
				"Employee",
				employee,
				"attendance_device_id",
				device_id,
				update_modified=False,
			)
