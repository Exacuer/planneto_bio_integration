# OLD CODE
# import requests
# import frappe
# from frappe import _
# from frappe.model.document import Document
# from frappe.utils import now_datetime


# class eSSLIntegrationSettings(Document):
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




# NEW CODE
# Copyright (c) 2026, Administrator and contributors
# For license information, please see license.txt

import requests
import frappe

from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime, get_datetime


class eSSLIntegrationSettings(Document):

    @frappe.whitelist()
    def sync_punches(self):

        # ---------------------------------------------------------
        # 1. Validate configuration
        # ---------------------------------------------------------

        if not self.base_url:
            frappe.throw(_("Please configure Base URL."))

        if not self.username:
            frappe.throw(_("Please configure Username."))

        if not self.password:
            frappe.throw(_("Please configure Password."))

        enabled_devices = [
            d for d in (self.devices or [])
            if d.enabled
        ]

        if not enabled_devices:
            return {
                "synced_count": 0,
                "message": _("No enabled devices found to sync.")
            }

        # ---------------------------------------------------------
        # 2. Counters
        # ---------------------------------------------------------

        total_fetched = 0
        created_count = 0
        duplicate_count = 0
        employee_not_found = 0
        invalid_count = 0

        errors = []

        # ---------------------------------------------------------
        # 3. Prepare eSSL API URL
        # ---------------------------------------------------------

        base_url = self.base_url.strip().rstrip("/")

        # Your current Base URL:
        #
        # http://43.241.31.104:85/iclock
        #
        # API:
        #
        # http://43.241.31.104:85/iclock/WebAPIService.asmx

        if base_url.lower().endswith("/iclock"):
            api_url = base_url + "/WebAPIService.asmx"
        elif base_url.lower().endswith("webapiservice.asmx"):
            api_url = base_url
        else:
            api_url = base_url + "/iclock/WebAPIService.asmx"

        # ---------------------------------------------------------
        # 4. Date range
        # ---------------------------------------------------------

        # First sync: fetch today's records.
        #
        # After that, we fetch from the previous sync time.
        #

        current_time = now_datetime()

        last_sync = None

        for device in enabled_devices:
            if device.last_synced_at:
                if not last_sync or get_datetime(device.last_synced_at) < last_sync:
                    last_sync = get_datetime(device.last_synced_at)

        if last_sync:
            from_time = last_sync
        else:
            # First sync - today's beginning
            from_time = current_time.replace(
                hour=0,
                minute=0,
                second=0,
                microsecond=0
            )

        to_time = current_time

        from_time_str = from_time.strftime("%Y-%m-%d %H:%M:%S")
        to_time_str = to_time.strftime("%Y-%m-%d %H:%M:%S")

        # ---------------------------------------------------------
        # 5. Sync every enabled device
        # ---------------------------------------------------------

        for device in enabled_devices:

            serial_number = (device.serial_number or "").strip()

            if not serial_number:
                errors.append(
                    _("Device {0}: Serial Number is missing.")
                    .format(device.device_label or device.name)
                )
                continue

            try:

                # -------------------------------------------------
                # SOAP request
                # -------------------------------------------------

                soap_body = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:xsd="http://www.w3.org/2001/XMLSchema"
    xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">

    <soap:Body>

        <GetTransactionsLog xmlns="http://tempuri.org/">

            <FromDateTime>{from_time_str}</FromDateTime>

            <ToDateTime>{to_time_str}</ToDateTime>

            <SerialNumber>{serial_number}</SerialNumber>

            <UserName>{self.username}</UserName>

            <UserPassword>{self.password}</UserPassword>

            <strDataList></strDataList>

        </GetTransactionsLog>

    </soap:Body>

</soap:Envelope>
"""

                headers = {
                    "Content-Type": "text/xml; charset=utf-8",
                    "SOAPAction": '"http://tempuri.org/GetTransactionsLog"',
                }

                response = requests.post(
                    api_url,
                    data=soap_body,
                    headers=headers,
                    timeout=60
                )

                # -------------------------------------------------
                # HTTP error
                # -------------------------------------------------

                if response.status_code != 200:

                    errors.append(
                        _(
                            "Device {0}: eSSL API returned HTTP {1}"
                        ).format(
                            serial_number,
                            response.status_code
                        )
                    )

                    continue

                # -------------------------------------------------
                # Parse XML
                # -------------------------------------------------

                from xml.etree import ElementTree as ET

                root = ET.fromstring(response.content)

                str_data_element = root.find(
                    ".//{http://tempuri.org/}strDataList"
                )

                if str_data_element is None:

                    errors.append(
                        _(
                            "Device {0}: eSSL returned no strDataList."
                        ).format(serial_number)
                    )

                    continue

                if not str_data_element.text:

                    device.last_synced_at = current_time
                    continue

                # -------------------------------------------------
                # eSSL returns tab-separated lines
                # -------------------------------------------------

                raw_logs = str_data_element.text.strip().splitlines()

                for raw_log in raw_logs:

                    raw_log = raw_log.strip()

                    if not raw_log:
                        continue

                    fields = raw_log.split("\t")

                    total_fetched += 1

                    # -------------------------------------------------
                    # Typical eSSL response:
                    #
                    # User ID
                    # Punch DateTime
                    # Verification / extra data
                    #
                    # Example:
                    #
                    # 168
                    # 2026-09-21 14:34:32
                    # ...
                    # -------------------------------------------------

                    if len(fields) < 2:
                        invalid_count += 1
                        continue

                    user_id = fields[0].strip()
                    punch_time = fields[1].strip()

                    if not user_id or not punch_time:
                        invalid_count += 1
                        continue

                    # -------------------------------------------------
                    # Parse punch datetime
                    # -------------------------------------------------

                    try:

                        punch_datetime = get_datetime(punch_time)

                    except Exception:

                        invalid_count += 1
                        continue

                    # -------------------------------------------------
                    # Find Employee
                    #
                    # Attendance Device ID = eSSL User ID
                    # -------------------------------------------------

                    employee_name = frappe.db.get_value(
                        "Employee",
                        {
                            "attendance_device_id": user_id,
                            "status": "Active"
                        },
                        "name"
                    )

                    # -------------------------------------------------
                    # Fallback: convert to string comparison
                    # -------------------------------------------------

                    if not employee_name:

                        employee_name = frappe.db.sql(
                            """
                            SELECT name
                            FROM `tabEmployee`
                            WHERE attendance_device_id = %s
                            AND status = 'Active'
                            LIMIT 1
                            """,
                            (user_id,),
                            as_dict=False
                        )

                        employee_name = (
                            employee_name[0][0]
                            if employee_name
                            else None
                        )

                    # -------------------------------------------------
                    # Employee not found
                    # -------------------------------------------------

                    if not employee_name:

                        employee_not_found += 1

                        frappe.log_error(
                            title="eSSL Employee Not Found",
                            message=(
                                f"eSSL User ID: {user_id}\n"
                                f"Punch Time: {punch_time}\n"
                                f"Device: {serial_number}\n"
                                f"Raw Log: {raw_log}"
                            )
                        )

                        continue

                    # -------------------------------------------------
                    # Determine IN / OUT
                    #
                    # IMPORTANT:
                    #
                    # Some eSSL API versions return Att State
                    # in one of the later columns.
                    #
                    # Search all fields for Check-In / Check-Out.
                    # -------------------------------------------------

                    log_type = None

                    for field in fields:

                        value = field.strip().lower()

                        if value in (
                            "check-in",
                            "check in",
                            "in",
                            "in-time",
                            "in time"
                        ):
                            log_type = "IN"
                            break

                        if value in (
                            "check-out",
                            "check out",
                            "out",
                            "out-time",
                            "out time"
                        ):
                            log_type = "OUT"
                            break

                    # -------------------------------------------------
                    # If API does not provide Att State,
                    # don't guess here.
                    #
                    # ERPNext can still store the punch with
                    # log_type = None.
                    # -------------------------------------------------

                    # -------------------------------------------------
                    # Duplicate check
                    # -------------------------------------------------

                    filters = {
                        "employee": employee_name,
                        "time": punch_datetime
                    }

                    if frappe.db.exists(
                        "Employee Checkin",
                        filters
                    ):

                        duplicate_count += 1
                        continue

                    # -------------------------------------------------
                    # Create Employee Checkin
                    # -------------------------------------------------

                    checkin = frappe.get_doc({
                        "doctype": "Employee Checkin",
                        "employee": employee_name,
                        "time": punch_datetime,
                        "log_type": log_type,
                        "device_id": serial_number
                    })

                    checkin.insert(
                        ignore_permissions=True
                    )

                    created_count += 1

                # -------------------------------------------------
                # Update device sync time
                # -------------------------------------------------

                device.last_synced_at = current_time

            except Exception as e:

                errors.append(
                    _(
                        "Device {0}: {1}"
                    ).format(
                        serial_number,
                        str(e)
                    )
                )

                frappe.log_error(
                    title="eSSL Sync Error",
                    message=frappe.get_traceback()
                )

        # ---------------------------------------------------------
        # 6. Save last sync time
        # ---------------------------------------------------------

        self.save(
            ignore_permissions=True
        )

        frappe.db.commit()

        # ---------------------------------------------------------
        # 7. Prepare result
        # ---------------------------------------------------------

        message = _(
            "<b>eSSL Sync Completed</b><br><br>"
            "Devices: {0}<br>"
            "Records fetched: {1}<br>"
            "Employee Checkins created: {2}<br>"
            "Duplicates skipped: {3}<br>"
            "Employees not found: {4}<br>"
            "Invalid records: {5}"
        ).format(
            len(enabled_devices),
            total_fetched,
            created_count,
            duplicate_count,
            employee_not_found,
            invalid_count
        )

        if errors:

            message += "<br><br><b>Errors:</b><br>"

            for error in errors:
                message += f"• {error}<br>"

        return {
            "synced_count": created_count,
            "fetched_count": total_fetched,
            "created_count": created_count,
            "duplicate_count": duplicate_count,
            "employee_not_found": employee_not_found,
            "invalid_count": invalid_count,
            "errors": errors,
            "message": message
        }
