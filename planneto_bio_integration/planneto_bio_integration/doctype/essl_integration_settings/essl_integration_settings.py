# Copyright (c) 2026, Administrator and contributors
# For license information, please see license.txt

from urllib.parse import urlparse, urlunparse
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape
import hashlib

import frappe
import requests
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, get_datetime, now_datetime, time_diff_in_seconds
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
TEMPURI_NS = "http://tempuri.org/"
# eSSL GetTransactionsLog requires exactly: yyyy-MM-dd HH:mm
ESSL_DATETIME_FORMAT = "%Y-%m-%d %H:%M"
CONNECT_TIMEOUT = 8
READ_TIMEOUT = 120


class eSSLAPIError(Exception):
	"""Raised when the eSSL SOAP API returns a business or transport error."""


class eSSLIntegrationSettings(Document):

	@frappe.whitelist()
	def sync_punches(self):
		if not self.base_url:
			frappe.throw(_("Please configure Base URL."))

		try:
			username, password = self._get_api_credentials()
		except frappe.ValidationError:
			raise
		except Exception:
			self._log_error("eSSL: Could not decrypt password")
			frappe.throw(_("Could not read eSSL password. Please save Password again."))

		enabled_devices = [d for d in (self.devices or []) if d.enabled]
		if not enabled_devices:
			return {
				"synced_count": 0,
				"message": _("No enabled devices found to sync."),
			}

		total_fetched = 0
		created_count = 0
		duplicate_count = 0
		employee_not_found = 0
		invalid_count = 0
		raw_saved = 0
		errors = []
		debug_lines = []
		self._logged_missing_employees = set()

		api_url = self._get_api_url()
		current_time = now_datetime()

		for device in enabled_devices:
			serial_number = (device.serial_number or "").strip()
			if not serial_number:
				errors.append(
					_("Device {0}: Serial Number is missing.").format(
						device.device_label or device.name
					)
				)
				continue

			from_time = self._get_from_time(device, current_time)
			to_time = current_time
			from_time_str = from_time.strftime(ESSL_DATETIME_FORMAT)
			to_time_str = to_time.strftime(ESSL_DATETIME_FORMAT)

			try:
				result_text, punch_text = self._fetch_device_logs(
					api_url=api_url,
					username=username,
					password=password,
					serial_number=serial_number,
					from_time_str=from_time_str,
					to_time_str=to_time_str,
				)

				debug_lines.append(
					_("Device {0}: {1} to {2}. URL: {3}. Result: {4}").format(
						serial_number,
						from_time_str,
						to_time_str,
						api_url,
						(result_text or _("empty"))[:160],
					)
				)

				if not punch_text:
					debug_lines.append(
						_("Device {0}: API returned no punch rows in strDataList.").format(
							serial_number
						)
					)
					device.last_synced_at = current_time
					continue

				raw_logs = [line.strip() for line in punch_text.splitlines() if line.strip()]
				if raw_logs:
					debug_lines.append(
						_("Device {0}: first row: {1}").format(serial_number, raw_logs[0][:200])
					)

				for raw_log in raw_logs:
					total_fetched += 1
					try:
						fetched, created, duplicate, missing, invalid, raw = self._process_raw_log(
							raw_log=raw_log,
							serial_number=serial_number,
						)
						created_count += created
						duplicate_count += duplicate
						employee_not_found += missing
						invalid_count += invalid
						raw_saved += raw
						if invalid and not created and not duplicate and not missing:
							errors.append(
								_("Device {0}: skipped invalid punch: {1}").format(
									serial_number, raw_log[:120]
								)
							)
					except Exception as e:
						invalid_count += 1
						errors.append(
							_("Device {0}: punch failed: {1}").format(serial_number, str(e))
						)
						self._log_error(
							"eSSL: Punch processing failed",
							serial_number=serial_number,
							raw_log=raw_log,
							error=str(e),
						)

				device.last_synced_at = current_time

			except eSSLAPIError as e:
				errors.append(_("Device {0}: {1}").format(serial_number, str(e)))
				debug_lines.append(_("Device {0}: {1}").format(serial_number, str(e)))
			except requests.exceptions.ConnectTimeout:
				message = self._connection_error_message(api_url)
				errors.append(_("Device {0}: {1}").format(serial_number, message))
				self._log_error(
					"eSSL: Connect timeout",
					api_url=api_url,
					serial_number=serial_number,
					from_time=from_time_str,
					to_time=to_time_str,
				)
			except requests.exceptions.ReadTimeout:
				message = _(
					"Device {0}: eSSL connected but did not respond in {1} seconds."
				).format(serial_number, READ_TIMEOUT)
				errors.append(message)
				self._log_error(
					"eSSL: Read timeout",
					api_url=api_url,
					serial_number=serial_number,
					from_time=from_time_str,
					to_time=to_time_str,
				)
			except requests.ConnectionError as e:
				message = self._connection_error_message(api_url)
				errors.append(_("Device {0}: {1}").format(serial_number, message))
				self._log_error(
					"eSSL: Connection failed",
					api_url=api_url,
					serial_number=serial_number,
					error=str(e),
				)
			except Exception as e:
				errors.append(_("Device {0}: {1}").format(serial_number, str(e)))
				self._log_error(
					"eSSL: Sync failed",
					api_url=api_url,
					serial_number=serial_number,
					from_time=from_time_str,
					to_time=to_time_str,
					error=str(e),
				)

		try:
			self.save(ignore_permissions=True)
			frappe.db.commit()
		except Exception:
			self._log_error("eSSL: Could not save last synced time")
			raise

		has_errors = bool(errors)
		message = _(
			"Devices: {0}<br>"
			"Records fetched: {1}<br>"
			"Raw punches saved: {2}<br>"
			"Employee Checkins created: {3}<br>"
			"Duplicates skipped: {4}<br>"
			"Employees not found: {5}<br>"
			"Invalid records: {6}"
		).format(
			len(enabled_devices),
			total_fetched,
			raw_saved,
			created_count,
			duplicate_count,
			employee_not_found,
			invalid_count,
		)

		return {
			"synced_count": created_count,
			"fetched_count": total_fetched,
			"created_count": created_count,
			"duplicate_count": duplicate_count,
			"employee_not_found": employee_not_found,
			"invalid_count": invalid_count,
			"errors": errors,
			"message": message,
		}

	@frappe.whitelist()
	def link_raw_punches(self):
		"""Link existing eSSL Raw Punch rows to Employee and create missing checkins."""
		linked = 0
		checkins_created = 0
		duplicates = 0
		still_missing = 0
		device_ids_updated = 0

		rows = frappe.get_all(
			"eSSL Raw Punch",
			fields=[
				"name",
				"attendance_device_id",
				"employee",
				"punch_time",
				"device_serial",
				"log_type",
			],
			order_by="punch_time asc",
			limit_page_length=10000,
		)

		for row in rows:
			device_id = (row.attendance_device_id or "").strip()
			employee = row.employee

			if not employee and device_id:
				employee = self._find_employee(device_id)
				if employee:
					frappe.db.set_value(
						"eSSL Raw Punch",
						row.name,
						"employee",
						employee,
						update_modified=False,
					)
					linked += 1

			if employee and device_id:
				current = frappe.db.get_value("Employee", employee, "attendance_device_id")
				if not current:
					frappe.db.set_value(
						"Employee",
						employee,
						"attendance_device_id",
						device_id,
						update_modified=False,
					)
					device_ids_updated += 1

			if not employee:
				still_missing += 1
				continue

			if frappe.db.exists(
				"Employee Checkin",
				{"employee": employee, "time": row.punch_time},
			):
				duplicates += 1
				continue

			log_type = (row.log_type or "").strip().upper()
			if log_type not in {"IN", "OUT"}:
				log_type = self._resolve_log_type(employee, row.punch_time, [])

			created, duplicate, error = self._create_checkin(
				employee_name=employee,
				punch_datetime=row.punch_time,
				log_type=log_type,
				serial_number=row.device_serial,
			)
			if created:
				checkins_created += 1
			elif duplicate:
				duplicates += 1
			elif error:
				self._log_error(
					"eSSL: Link raw punch checkin failed",
					raw_punch=row.name,
					employee=employee,
					error=error,
				)

		frappe.db.commit()

		message = _(
			"Raw punches linked to Employee: {0}<br>"
			"Employee Attendance Device IDs set: {1}<br>"
			"Employee Checkins created: {2}<br>"
			"Already existed / duplicates: {3}<br>"
			"Still without Employee: {4}"
		).format(linked, device_ids_updated, checkins_created, duplicates, still_missing)

		return {
			"linked": linked,
			"device_ids_updated": device_ids_updated,
			"checkins_created": checkins_created,
			"duplicates": duplicates,
			"still_missing": still_missing,
			"message": message,
		}

	@frappe.whitelist()
	def test_connection(self):
		if not self.base_url:
			frappe.throw(_("Please configure Base URL."))

		username, password = self._get_api_credentials()
		api_url = self._get_api_url()
		serial_number = ""
		for device in self.devices or []:
			if device.enabled and (device.serial_number or "").strip():
				serial_number = device.serial_number.strip()
				break

		now = now_datetime()
		from_time_str = now.strftime(ESSL_DATETIME_FORMAT)
		to_time_str = from_time_str

		try:
			result_text, _punch_text = self._fetch_device_logs(
				api_url=api_url,
				username=username,
				password=password,
				serial_number=serial_number or "TEST",
				from_time_str=from_time_str,
				to_time_str=to_time_str,
			)
		except eSSLAPIError as e:
			frappe.throw(_("eSSL login failed: {0}").format(str(e)))
		except requests.exceptions.ConnectTimeout:
			frappe.throw(self._connection_error_message(api_url))
		except requests.ConnectionError:
			frappe.throw(self._connection_error_message(api_url))
		except Exception as e:
			self._log_error("eSSL: Test connection failed", api_url=api_url, error=str(e))
			frappe.throw(_("Could not reach eSSL API: {0}").format(str(e)))

		return {
			"ok": True,
			"message": _("Logged in to {0} as {1}. Result: {2}").format(
				api_url, username, result_text or _("OK")
			),
		}

	def on_update(self):
		if cint(self.enable_auto_sync) and (
			self.has_value_changed("enable_auto_sync")
			or self.has_value_changed("auto_sync_interval")
		):
			_enqueue_next_auto_sync(cint(self.auto_sync_interval) or 60)

	def _get_api_credentials(self):
		username = (self.username or "").strip()
		if not username:
			frappe.throw(_("Please configure Username."))

		# Never use the form value. Desk sends a masked string like "****",
		# which eSSL rejects as Unathorised User.
		password = self.get_password("password")
		if not password or self.is_dummy_password(password):
			frappe.throw(_("Please enter and save the eSSL password again."))

		return username, password

	def _get_api_url(self):
		raw = (self.base_url or "").strip()
		if not raw:
			frappe.throw(_("Please configure Base URL."))
		if "://" not in raw:
			raw = "http://" + raw

		parsed = urlparse(raw)
		path = parsed.path or ""
		lower = path.lower()
		scheme = parsed.scheme or "http"
		netloc = parsed.netloc

		if "webapiservice.asmx" in lower:
			end = lower.find("webapiservice.asmx") + len("webapiservice.asmx")
			return urlunparse((scheme, netloc, path[:end], "", "", ""))

		if "/iclock" in lower:
			prefix = path[: lower.find("/iclock")]
			return urlunparse((scheme, netloc, prefix + "/iclock/WebAPIService.asmx", "", "", ""))

		return urlunparse((scheme, netloc, "/iclock/WebAPIService.asmx", "", "", ""))

	def _connection_error_message(self, api_url):
		return _(
			"Cannot connect to {0}. eTimeTrackLite can show punches while Frappe still "
			"fails if this server cannot open that IP/port. Use a LAN URL if you are "
			"on the same network, and allow port 85 from this Frappe host."
		).format(api_url)

	@staticmethod
	def _auth_error_message(result_text, username, password):
		lowered = (result_text or "").lower()
		if "unathor" in lowered or "unauthor" in lowered:
			return _(
				"eSSL rejected user '{0}'. The screen login essl/essl is not the Web API login. "
				"Open eTimeTrackLite → API Settings, copy that API username and password, "
				"paste them here, Save, then Sync. eSSL message: {1}"
			).format(username, result_text)
		return result_text

	@staticmethod
	def _http_session():
		session = requests.Session()
		session.mount(
			"http://",
			HTTPAdapter(max_retries=Retry(total=0, connect=0, read=0, redirect=0)),
		)
		session.mount(
			"https://",
			HTTPAdapter(max_retries=Retry(total=0, connect=0, read=0, redirect=0)),
		)
		return session

	@staticmethod
	def _get_from_time(device, current_time):
		start_of_today = current_time.replace(hour=0, minute=0, second=0, microsecond=0)
		if not device.last_synced_at:
			return start_of_today

		last_sync_day = get_datetime(device.last_synced_at).replace(
			hour=0, minute=0, second=0, microsecond=0
		)
		# Re-fetch from the last sync day so a failed earlier sync does not drop punches.
		return min(last_sync_day, start_of_today)

	def _fetch_device_logs(
		self, api_url, username, password, serial_number, from_time_str, to_time_str
	):
		last_error = None
		for password_to_send, password_mode in self._password_attempts(password):
			try:
				response = self._post_transactions_log(
					api_url=api_url,
					username=username,
					password=password_to_send,
					serial_number=serial_number,
					from_time_str=from_time_str,
					to_time_str=to_time_str,
				)
			except (requests.exceptions.ConnectTimeout, requests.ConnectionError):
				# Host is unreachable — retrying plain/MD5 passwords only wastes time.
				raise

			result_text, punch_text = self._parse_transactions_response(
				response=response,
				api_url=api_url,
				username=username,
				password=password_to_send,
				password_mode=password_mode,
				serial_number=serial_number,
				from_time_str=from_time_str,
				to_time_str=to_time_str,
			)
			if self._is_auth_failure(result_text) and not punch_text:
				last_error = result_text
				continue
			if not punch_text and result_text and not self._is_essl_success(result_text):
				raise eSSLAPIError(
					self._auth_error_message(result_text, username, password)
				)
			return result_text, punch_text

		raise eSSLAPIError(self._auth_error_message(last_error, username, password))

	def _parse_transactions_response(
		self,
		response,
		api_url,
		username,
		password,
		password_mode,
		serial_number,
		from_time_str,
		to_time_str,
	):
		if response.status_code != 200:
			self._log_error(
				"eSSL: HTTP error",
				api_url=api_url,
				serial_number=serial_number,
				from_time=from_time_str,
				to_time=to_time_str,
				http_status=response.status_code,
				response=self._safe_response_text(response),
			)
			raise eSSLAPIError(_("eSSL API returned HTTP {0}").format(response.status_code))

		content_type = (response.headers.get("Content-Type") or "").lower()
		body_start = (response.text or "").lstrip()[:80].lower()
		if "text/html" in content_type or body_start.startswith("<!doctype") or body_start.startswith("<html"):
			self._log_error(
				"eSSL: HTML instead of SOAP",
				api_url=api_url,
				serial_number=serial_number,
				content_type=content_type,
				response=self._safe_response_text(response),
			)
			raise eSSLAPIError(
				_("eSSL URL is a web page, not the SOAP API: {0}").format(api_url)
			)

		try:
			root = ET.fromstring(response.content)
		except ET.ParseError as e:
			self._log_error(
				"eSSL: Invalid XML response",
				api_url=api_url,
				serial_number=serial_number,
				from_time=from_time_str,
				to_time=to_time_str,
				error=str(e),
				response=self._safe_response_text(response),
			)
			raise eSSLAPIError(_("eSSL returned invalid XML.")) from e

		fault = root.find(f".//{{{SOAP_NS}}}Fault")
		if fault is not None:
			fault_text = "".join(fault.itertext()).strip() or "SOAP Fault"
			self._log_error(
				"eSSL: SOAP Fault",
				api_url=api_url,
				serial_number=serial_number,
				from_time=from_time_str,
				to_time=to_time_str,
				error=fault_text,
				response=self._safe_response_text(response),
			)
			raise eSSLAPIError(fault_text)

		result_element = root.find(f".//{{{TEMPURI_NS}}}GetTransactionsLogResult")
		str_data_element = root.find(f".//{{{TEMPURI_NS}}}strDataList")
		result_text = (result_element.text or "").strip() if result_element is not None else ""
		punch_text = (str_data_element.text or "").strip() if str_data_element is not None else ""

		if not punch_text and self._looks_like_punch_log(result_text):
			punch_text = result_text
			result_text = "OK"

		if not punch_text and result_text and not self._is_essl_success(result_text):
			self._log_error(
				"eSSL: API rejected request",
				api_url=api_url,
				serial_number=serial_number,
				from_time=from_time_str,
				to_time=to_time_str,
				username=username,
				password_mode=password_mode,
				password_length=len(password or ""),
				result=result_text,
				response=self._safe_response_text(response),
			)

		return result_text, punch_text

	@staticmethod
	def _password_attempts(password):
		# Official samples send the plain System User password.
		# Some iclock builds store MD5 in SQL and compare the hash.
		yield password, "plain"
		md5_hex = hashlib.md5(password.encode("utf-8")).hexdigest()
		yield md5_hex, "md5"
		yield md5_hex.upper(), "md5_upper"

	@staticmethod
	def _is_auth_failure(result_text):
		lowered = (result_text or "").lower()
		return "unathor" in lowered or "unauthor" in lowered

	def _post_transactions_log(
		self, api_url, username, password, serial_number, from_time_str, to_time_str
	):
		soap_body = (
			'<?xml version="1.0" encoding="utf-8"?>'
			'<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
			' xmlns:xsd="http://www.w3.org/2001/XMLSchema"'
			' xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
			"<soap:Body>"
			'<GetTransactionsLog xmlns="http://tempuri.org/">'
			f"<FromDateTime>{escape(from_time_str)}</FromDateTime>"
			f"<ToDateTime>{escape(to_time_str)}</ToDateTime>"
			f"<SerialNumber>{escape(serial_number)}</SerialNumber>"
			f"<UserName>{escape(username)}</UserName>"
			f"<UserPassword>{escape(password)}</UserPassword>"
			"<strDataList></strDataList>"
			"</GetTransactionsLog>"
			"</soap:Body>"
			"</soap:Envelope>"
		)

		return self._http_session().post(
			api_url,
			data=soap_body.encode("utf-8"),
			headers={
				"Content-Type": "text/xml; charset=utf-8",
				"SOAPAction": '"http://tempuri.org/GetTransactionsLog"',
			},
			timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
		)

	def _process_raw_log(self, raw_log, serial_number):
		fields = self._split_log_fields(raw_log)
		parsed = self._parse_punch_fields(fields)
		if not parsed:
			self._log_error(
				"eSSL: Invalid punch row",
				serial_number=serial_number,
				raw_log=raw_log,
			)
			return 1, 0, 0, 0, 1, 0

		user_id, punch_datetime = parsed
		employee_name = self._find_employee(user_id)
		log_type = self._resolve_log_type(employee_name, punch_datetime, fields)
		raw_saved = 0

		try:
			if self._save_raw_punch(
				user_id=user_id,
				employee_name=employee_name,
				punch_datetime=punch_datetime,
				serial_number=serial_number,
				log_type=log_type,
			):
				raw_saved = 1
		except Exception as e:
			self._log_error(
				"eSSL: Could not save raw punch",
				serial_number=serial_number,
				user_id=user_id,
				punch_time=str(punch_datetime),
				error=str(e),
			)

		if not employee_name:
			if user_id not in getattr(self, "_logged_missing_employees", set()):
				self._logged_missing_employees = getattr(
					self, "_logged_missing_employees", set()
				)
				self._logged_missing_employees.add(user_id)
				self._log_error(
					"eSSL: Employee not found",
					serial_number=serial_number,
					user_id=user_id,
					punch_time=str(punch_datetime),
					raw_log=raw_log,
				)
			return 1, 0, 0, 1, 0, raw_saved

		existing = frappe.db.get_value(
			"Employee Checkin",
			{"employee": employee_name, "time": punch_datetime},
			["name", "log_type"],
			as_dict=True,
		)
		if existing:
			if existing.log_type != log_type:
				frappe.db.set_value(
					"Employee Checkin",
					existing.name,
					"log_type",
					log_type,
					update_modified=False,
				)
			return 1, 0, 1, 0, 0, raw_saved

		created, duplicate, error = self._create_checkin(
			employee_name=employee_name,
			punch_datetime=punch_datetime,
			log_type=log_type,
			serial_number=serial_number,
		)
		if error:
			self._log_error(
				"eSSL: Could not create Employee Checkin",
				serial_number=serial_number,
				employee=employee_name,
				user_id=user_id,
				punch_time=str(punch_datetime),
				error=error,
			)
			return 1, 0, 0, 0, 1, raw_saved

		return 1, int(created), int(duplicate), 0, 0, raw_saved

	@staticmethod
	def _split_log_fields(raw_log):
		if "\t" in raw_log:
			return [part.strip() for part in raw_log.split("\t")]
		if "," in raw_log:
			return [part.strip() for part in raw_log.split(",")]
		return raw_log.split()

	@staticmethod
	def _parse_punch_fields(fields):
		if len(fields) < 2:
			return None

		user_id = fields[0].strip()
		punch_time = fields[1].strip()
		if not user_id or not punch_time:
			return None

		try:
			punch_datetime = get_datetime(punch_time)
		except Exception:
			return None

		if not punch_datetime:
			return None

		return user_id, punch_datetime

	@staticmethod
	def _parse_log_type(fields):
		text_in = {"check-in", "check in", "in-time", "in time", "i"}
		text_out = {"check-out", "check out", "out", "out-time", "out time", "o"}

		for field in fields[2:]:
			value = field.strip().lower()
			if value in text_out or value in {"1", "out"}:
				return "OUT"
			if value in text_in or value == "0":
				return "IN"
			# Many INOUT devices always send "in" in strDataList even for Check-Out.
			if value == "in":
				return None

		if len(fields) >= 4 and fields[3].strip() in {"0", "1"}:
			return "IN" if fields[3].strip() == "0" else "OUT"

		return None

	@staticmethod
	def _resolve_log_type(employee_name, punch_datetime, fields):
		"""Use API Att State when reliable; otherwise alternate IN/OUT for INOUT devices."""
		parsed = eSSLIntegrationSettings._parse_log_type(fields)
		if parsed:
			return parsed

		if not employee_name:
			return "IN"

		last_log_type = frappe.db.get_value(
			"Employee Checkin",
			{
				"employee": employee_name,
				"time": ("<", punch_datetime),
			},
			"log_type",
			order_by="time desc",
		)
		if last_log_type == "IN":
			return "OUT"
		return "IN"

	@staticmethod
	def _find_employee(user_id):
		"""Match eSSL Device User ID to Employee.attendance_device_id, then Employee.name."""
		user_id = (user_id or "").strip()
		if not user_id:
			return None

		candidates = [user_id]
		if user_id.isdigit():
			candidates.append(str(int(user_id)))

		for candidate in dict.fromkeys(candidates):
			employee_name = frappe.db.get_value(
				"Employee",
				{"attendance_device_id": candidate},
				"name",
			)
			if employee_name:
				return employee_name

		rows = frappe.db.sql(
			"""
			SELECT name
			FROM `tabEmployee`
			WHERE TRIM(IFNULL(attendance_device_id, '')) = %s
			LIMIT 1
			""",
			(user_id,),
		)
		if rows:
			return rows[0][0]

		# Many sites keep the eSSL User ID as Employee ID (name).
		for candidate in dict.fromkeys(candidates):
			if frappe.db.exists("Employee", candidate):
				eSSLIntegrationSettings._ensure_attendance_device_id(candidate, user_id)
				return candidate

		return None

	@staticmethod
	def _ensure_attendance_device_id(employee_name, user_id):
		"""Store eSSL User ID on Employee.attendance_device_id when blank."""
		current = frappe.db.get_value("Employee", employee_name, "attendance_device_id")
		if current:
			return
		frappe.db.set_value(
			"Employee",
			employee_name,
			"attendance_device_id",
			user_id,
			update_modified=False,
		)

	@staticmethod
	def _save_raw_punch(user_id, employee_name, punch_datetime, serial_number, log_type=None):
		dedup_key = f"{user_id}|{punch_datetime}|{serial_number}"
		existing = frappe.db.get_value(
			"eSSL Raw Punch",
			{"dedup_key": dedup_key},
			["name", "log_type", "employee"],
			as_dict=True,
		)
		if existing:
			updates = {}
			if log_type and existing.log_type != log_type:
				updates["log_type"] = log_type
			if employee_name and not existing.employee:
				updates["employee"] = employee_name
			if updates:
				frappe.db.set_value(
					"eSSL Raw Punch", existing.name, updates, update_modified=False
				)
			return False

		doc = frappe.get_doc(
			{
				"doctype": "eSSL Raw Punch",
				"attendance_device_id": user_id,
				"employee": employee_name,
				"punch_time": punch_datetime,
				"log_type": log_type,
				"device_serial": serial_number,
				"dedup_key": dedup_key,
			}
		)
		doc.insert(ignore_permissions=True)
		return True

	@staticmethod
	def _create_checkin(employee_name, punch_datetime, log_type, serial_number):
		checkin = frappe.get_doc(
			{
				"doctype": "Employee Checkin",
				"employee": employee_name,
				"time": punch_datetime,
				"log_type": log_type or "IN",
				"device_id": serial_number,
			}
		)

		try:
			checkin.insert(ignore_permissions=True)
			return True, False, None
		except frappe.DuplicateEntryError:
			return False, True, None
		except frappe.ValidationError as e:
			message = str(e)
			if "already has a log" in message.lower():
				return False, True, None

			try:
				checkin.flags.ignore_validate = True
				checkin.insert(ignore_permissions=True)
				return True, False, None
			except Exception:
				return False, False, message
		except Exception as e:
			return False, False, str(e)

	def _log_error(self, title, **context):
		lines = []
		for key, value in context.items():
			if value is None or value == "":
				continue
			lines.append(f"{key}: {value}")

		traceback = frappe.get_traceback()
		if traceback:
			lines.append("")
			lines.append(traceback)

		try:
			frappe.log_error(
				title=title[:140],
				message="\n".join(lines) or title,
				reference_doctype=self.doctype,
				reference_name=self.name,
			)
		except Exception:
			frappe.log_error(title=title[:140], message="\n".join(lines) or title)

	@staticmethod
	def _safe_response_text(response):
		try:
			text = response.text or ""
		except Exception:
			text = str(response.content[:2000])
		return text[:2000]

	@staticmethod
	def _is_essl_success(result_text):
		if not result_text:
			return True
		lowered = result_text.strip().lower()
		if lowered.isdigit():
			return True
		if lowered.startswith("logs count"):
			return True
		return lowered in {"success", "true", "ok", "pass", "yes"}

	@staticmethod
	def _looks_like_punch_log(text):
		if not text:
			return False
		return "\t" in text or "\n" in text


def auto_sync_essl_punches():
	"""Sync punches when Auto Sync is enabled (interval in seconds)."""
	if not frappe.db.exists("DocType", "eSSL Integration Settings"):
		return

	settings = frappe.get_single("eSSL Integration Settings")
	if not cint(settings.enable_auto_sync):
		return

	if not settings.base_url or not settings.username:
		return

	interval_seconds = cint(settings.auto_sync_interval) or 60
	if settings.last_auto_sync_at:
		elapsed = time_diff_in_seconds(
			now_datetime(), get_datetime(settings.last_auto_sync_at)
		)
		if elapsed < interval_seconds:
			_enqueue_next_auto_sync(interval_seconds)
			return

	try:
		settings.flags.ignore_permissions = True
		result = settings.sync_punches()
		frappe.db.set_single_value(
			"eSSL Integration Settings",
			"last_auto_sync_at",
			now_datetime(),
		)
		frappe.db.commit()

		if result and result.get("errors"):
			frappe.log_error(
				title="eSSL Auto Sync warning",
				message="\n".join(result.get("errors") or []),
				reference_doctype="eSSL Integration Settings",
				reference_name="eSSL Integration Settings",
			)
	except Exception:
		frappe.log_error(
			title="eSSL Auto Sync Failed",
			message=frappe.get_traceback(),
			reference_doctype="eSSL Integration Settings",
			reference_name="eSSL Integration Settings",
		)
	finally:
		_enqueue_next_auto_sync(interval_seconds)


def _enqueue_next_auto_sync(interval_seconds):
	"""Queue the next auto sync after the selected seconds."""
	try:
		frappe.enqueue(
			"planneto_bio_integration.planneto_bio_integration.doctype.essl_integration_settings.essl_integration_settings.auto_sync_essl_punches",
			queue="short",
			timeout=max(cint(interval_seconds) + READ_TIMEOUT + 60, 180),
			enqueue_after_seconds=max(cint(interval_seconds), 30),
			job_id="planneto_essl_auto_sync",
			deduplicate=True,
		)
	except Exception:
		pass

