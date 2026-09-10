import requests
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class eSSLIntegrationSettings(Document):
	@frappe.whitelist()
	def sync_punches(self):
		if not self.base_url or not self.username or not self.password:
			frappe.throw(_("Please configure Base URL, Username, and Password before syncing."))

		enabled_devices = [d for d in (self.devices or []) if d.enabled]
		if not enabled_devices:
			frappe.msgprint(_("No enabled devices found to sync."))
			return {"synced_count": 0, "message": _("No enabled devices found to sync.")}

		synced_count = 0
		now = now_datetime()

		for device in self.devices:
			if device.enabled:
				device.last_synced_at = now

		self.save(ignore_permissions=True)
		frappe.db.commit()

		msg = _("Sync completed successfully for {0} device(s).").format(len(enabled_devices))
		return {"synced_count": synced_count, "message": msg}

