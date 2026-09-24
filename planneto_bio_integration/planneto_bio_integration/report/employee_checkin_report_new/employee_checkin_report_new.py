# Copyright (c) 2026, Administrator and contributors
# For license information, please see license.txt

"""Employee Checkin Report NEW — aligned to Nighoje Plant attendance policy.

Policy highlights applied here:
- Biometric IN and OUT are mandatory
- First punch of the day = IN, last punch = OUT
- Single punch → day treated as Absent (cannot determine IN/OUT)
- 15-minute grace from shift start for late coming
- Late mark when first punch is after shift start + grace
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import (
	add_days,
	cint,
	formatdate,
	get_datetime,
	getdate,
	time_diff_in_hours,
	time_diff_in_seconds,
)

DEFAULT_GRACE_MINUTES = 15

# Fallback shift timings (HH:MM) when Shift Type is missing on the checkin/employee.
SHIFT_TIMINGS = {
	"GENERAL SHIFT (A)": ("08:30:00", "17:45:00"),
	"GENERAL SHIFT (B)": ("08:30:00", "17:00:00"),
	"FIRST SHIFT": ("07:00:00", "15:30:00"),
	"SECOND SHIFT": ("15:30:00", "00:00:00"),
	"THIRD SHIFT": ("00:00:00", "07:00:00"),
	"DAY SHIFT": ("08:00:00", "16:30:00"),
	"NIGHT SHIFT": ("20:00:00", "04:30:00"),
}


def execute(filters=None):
	filters = frappe._dict(filters or {})
	validate_filters(filters)

	# Policy view is the daily attendance summary.
	if cint(filters.get("punch_log_view")):
		columns = get_detail_columns()
		data = get_detail_data(filters)
	else:
		columns = get_summary_columns()
		data = get_summary_data(filters)

	chart = get_chart_data(filters, data)
	report_summary = get_report_summary(filters, data)

	return columns, data, None, chart, report_summary


def validate_filters(filters):
	if not filters.get("from_date") or not filters.get("to_date"):
		frappe.throw(_("From Date and To Date are required"))

	if getdate(filters.from_date) > getdate(filters.to_date):
		frappe.throw(_("From Date cannot be after To Date"))

	if filters.get("grace_minutes") in (None, ""):
		filters.grace_minutes = DEFAULT_GRACE_MINUTES


def get_detail_columns():
	return [
		{"label": _("Date"), "fieldname": "punch_date", "fieldtype": "Date", "width": 110},
		{
			"label": _("Employee"),
			"fieldname": "employee",
			"fieldtype": "Link",
			"options": "Employee",
			"width": 120,
		},
		{"label": _("Employee Name"), "fieldname": "employee_name", "fieldtype": "Data", "width": 180},
		{
			"label": _("Department"),
			"fieldname": "department",
			"fieldtype": "Link",
			"options": "Department",
			"width": 140,
		},
		{
			"label": _("Shift"),
			"fieldname": "shift",
			"fieldtype": "Link",
			"options": "Shift Type",
			"width": 140,
		},
		{"label": _("Punch Role"), "fieldname": "punch_role", "fieldtype": "Data", "width": 100},
		{"label": _("Log Type"), "fieldname": "log_type", "fieldtype": "Data", "width": 90},
		{"label": _("Time"), "fieldname": "punch_time", "fieldtype": "Time", "width": 100},
		{
			"label": _("Checkin"),
			"fieldname": "name",
			"fieldtype": "Link",
			"options": "Employee Checkin",
			"width": 170,
		},
	]


def get_summary_columns():
	return [
		{"label": _("Date"), "fieldname": "punch_date", "fieldtype": "Date", "width": 100},
		{"label": _("Day"), "fieldname": "weekday", "fieldtype": "Data", "width": 90},
		{
			"label": _("Employee"),
			"fieldname": "employee",
			"fieldtype": "Link",
			"options": "Employee",
			"width": 110,
		},
		{"label": _("Employee Name"), "fieldname": "employee_name", "fieldtype": "Data", "width": 160},
		{
			"label": _("Department"),
			"fieldname": "department",
			"fieldtype": "Link",
			"options": "Department",
			"width": 130,
		},
		{
			"label": _("Shift"),
			"fieldname": "shift",
			"fieldtype": "Link",
			"options": "Shift Type",
			"width": 140,
		},
		{"label": _("Shift Start"), "fieldname": "shift_start", "fieldtype": "Time", "width": 100},
		{"label": _("First Punch (IN)"), "fieldname": "first_in", "fieldtype": "Time", "width": 120},
		{"label": _("Last Punch (OUT)"), "fieldname": "last_out", "fieldtype": "Time", "width": 120},
		{"label": _("Punches"), "fieldname": "total_punches", "fieldtype": "Int", "width": 80},
		{
			"label": _("Hours Worked"),
			"fieldname": "hours_worked",
			"fieldtype": "Float",
			"width": 110,
			"precision": 2,
		},
		{"label": _("Late By (Mins)"), "fieldname": "late_by_mins", "fieldtype": "Int", "width": 110},
		{"label": _("Late Mark"), "fieldname": "late_mark", "fieldtype": "Data", "width": 90},
		{"label": _("Month Late Marks"), "fieldname": "month_late_marks", "fieldtype": "Int", "width": 120},
		{"label": _("Policy Status"), "fieldname": "policy_status", "fieldtype": "Data", "width": 160},
		{"label": _("Remarks"), "fieldname": "remarks", "fieldtype": "Data", "width": 220},
	]


def get_checkin_conditions(filters):
	conditions = ["ec.time between %(from_datetime)s and %(to_datetime)s"]
	values = {
		"from_datetime": f"{filters.from_date} 00:00:00",
		"to_datetime": f"{filters.to_date} 23:59:59",
	}

	if filters.get("employee"):
		conditions.append("ec.employee = %(employee)s")
		values["employee"] = filters.employee

	if filters.get("log_type"):
		conditions.append("ec.log_type = %(log_type)s")
		values["log_type"] = filters.log_type

	if filters.get("company"):
		conditions.append("emp.company = %(company)s")
		values["company"] = filters.company

	if filters.get("department"):
		conditions.append("emp.department = %(department)s")
		values["department"] = filters.department

	if filters.get("shift"):
		conditions.append(
			"""(
				ec.shift = %(shift)s
				or emp.default_shift = %(shift)s
			)"""
		)
		values["shift"] = filters.shift

	return " and ".join(conditions), values


def get_detail_data(filters):
	conditions, values = get_checkin_conditions(filters)
	rows = frappe.db.sql(
		f"""
		select
			date(ec.time) as punch_date,
			time(ec.time) as punch_time,
			ec.employee,
			ec.employee_name,
			emp.department,
			emp.designation,
			emp.branch,
			emp.default_shift,
			ec.log_type,
			ec.time,
			ec.shift,
			ec.attendance,
			ec.name
		from `tabEmployee Checkin` ec
		left join `tabEmployee` emp on emp.name = ec.employee
		where {conditions}
		order by ec.employee, ec.time asc
		""",
		values,
		as_dict=True,
	)

	# Annotate punch role by policy: first punch of day = IN, last = OUT.
	by_day = defaultdict(list)
	for row in rows:
		by_day[(row.punch_date, row.employee)].append(row)

	for day_rows in by_day.values():
		day_rows.sort(key=lambda r: get_datetime(r.time))
		for idx, row in enumerate(day_rows):
			if len(day_rows) == 1:
				row.punch_role = _("Single Punch")
			elif idx == 0:
				row.punch_role = _("IN (First)")
			elif idx == len(day_rows) - 1:
				row.punch_role = _("OUT (Last)")
			else:
				row.punch_role = _("Intermediate")

	# Newest first for browsing
	rows.sort(key=lambda r: get_datetime(r.time), reverse=True)
	return rows


def get_summary_data(filters):
	grace_minutes = cint(filters.get("grace_minutes") or DEFAULT_GRACE_MINUTES)
	detail_filters = frappe._dict({**filters, "log_type": None})
	detail_rows = get_detail_data(detail_filters)

	shift_cache = _load_shift_cache()
	assignment_cache = _load_shift_assignments(filters)
	leave_cache = _load_approved_leaves(filters)

	grouped = defaultdict(list)
	for row in detail_rows:
		grouped[(getdate(row.punch_date), row.employee)].append(row)

	# Build provisional rows first (without month late totals)
	provisional = []
	for (punch_date, employee), punches in grouped.items():
		punches = sorted(punches, key=lambda d: get_datetime(d.time))
		first = punches[0]
		all_times = [get_datetime(p.time) for p in punches]
		first_punch = all_times[0]
		last_punch = all_times[-1]
		total_punches = len(punches)

		shift_name, shift_source = _resolve_shift(
			employee=employee,
			punch_date=punch_date,
			checkin_shift=first.shift,
			default_shift=first.default_shift,
			assignment_cache=assignment_cache,
			fallback_shift=filters.get("fallback_shift"),
		)
		shift_start, shift_end = _get_shift_window(shift_name, punch_date, shift_cache)

		hours_worked = 0.0
		if total_punches >= 2 and last_punch > first_punch:
			hours_worked = round(time_diff_in_hours(last_punch, first_punch), 2)

		late_by_mins = 0
		late_mark = _("No")
		# Late marks apply only when both IN and OUT exist (valid attendance day)
		if shift_start and total_punches >= 2:
			grace_deadline = shift_start + timedelta(minutes=grace_minutes)
			if first_punch > grace_deadline:
				late_by_mins = cint(
					time_diff_in_seconds(first_punch, shift_start) / 60
				)
				late_mark = _("Yes")
		elif shift_start and total_punches == 1 and first_punch > (
			shift_start + timedelta(minutes=grace_minutes)
		):
			# Informational only — not counted as a late mark
			late_by_mins = cint(time_diff_in_seconds(first_punch, shift_start) / 60)

		on_leave = (employee, punch_date) in leave_cache
		policy_status, remarks = _evaluate_policy_status(
			total_punches=total_punches,
			first_punch=first_punch,
			last_punch=last_punch,
			late_mark=late_mark == _("Yes"),
			on_leave=on_leave,
			punch_date=punch_date,
			grace_minutes=grace_minutes,
			shift_source=shift_source,
			has_shift_window=bool(shift_start),
		)

		if filters.get("late_only") and late_mark != _("Yes"):
			continue
		if filters.get("policy_status") and policy_status != filters.policy_status:
			continue

		provisional.append(
			{
				"punch_date": punch_date,
				"weekday": formatdate(punch_date, "dddd"),
				"employee": employee,
				"employee_name": first.employee_name,
				"department": first.department,
				"shift": shift_name,
				"shift_start": shift_start.time() if shift_start else None,
				"first_in": first_punch.time() if first_punch else None,
				"last_out": last_punch.time() if total_punches >= 2 else None,
				"total_punches": total_punches,
				"hours_worked": hours_worked,
				"late_by_mins": late_by_mins,
				"late_mark": late_mark,
				"month_late_marks": 0,
				"policy_status": policy_status,
				"remarks": remarks,
				"_late_yes": 1 if late_mark == _("Yes") else 0,
			}
		)

	# Month-to-date late marks within selected range (and same calendar month as the row)
	lates_by_emp_month = defaultdict(list)
	for row in provisional:
		if row["_late_yes"]:
			lates_by_emp_month[
				(row["employee"], getdate(row["punch_date"]).year, getdate(row["punch_date"]).month)
			].append(getdate(row["punch_date"]))

	for key, dates in lates_by_emp_month.items():
		dates.sort()

	summary = []
	for row in provisional:
		emp = row["employee"]
		d = getdate(row["punch_date"])
		dates = lates_by_emp_month.get((emp, d.year, d.month), [])
		row["month_late_marks"] = len([x for x in dates if x <= d])
		# After 3 late marks/month, every 3 additional → ½ day leave deduction note
		if row["month_late_marks"] > 3 and row["_late_yes"]:
			extra = row["month_late_marks"] - 3
			half_days = extra // 3
			if half_days and _("½ day leave") not in row["remarks"]:
				row["remarks"] = (
					(row["remarks"] + "; " if row["remarks"] else "")
					+ _("Month late marks {0}: {1} × ½ day leave deduction due").format(
						row["month_late_marks"], half_days
					)
				)
		row.pop("_late_yes", None)
		summary.append(row)

	summary.sort(
		key=lambda d: (d["punch_date"] or getdate(), d["employee"] or ""),
		reverse=True,
	)
	return summary


def _evaluate_policy_status(
	total_punches,
	first_punch,
	last_punch,
	late_mark,
	on_leave,
	punch_date,
	grace_minutes=DEFAULT_GRACE_MINUTES,
	shift_source="",
	has_shift_window=False,
):
	notes = []

	if on_leave:
		return _("Present on Leave"), _("Approved leave — treated as Present on Leave")

	# Saturday policy note (alternate Saturdays / 5th Saturday working)
	if getdate(punch_date).weekday() == 5:
		week_no = (getdate(punch_date).day - 1) // 7 + 1
		if week_no == 5:
			notes.append(_("5th Saturday — working day for everyone"))
		else:
			notes.append(
				_("Saturday week {0} — confirm alternate Saturday roster (1st&3rd or 2nd&4th)").format(
					week_no
				)
			)

	if shift_source == "fallback":
		notes.append(_("Shift not assigned — using fallback shift for late calculation"))
	elif not has_shift_window:
		notes.append(_("Shift not assigned — map employee to working hours/shift"))

	def _join(base):
		if notes:
			return f"{base}. " + "; ".join(notes)
		return base

	if total_punches <= 0:
		return _("Absent"), _join(_("No biometric punches"))

	if total_punches == 1:
		return (
			_("Absent (Single Punch)"),
			_join(_("Only one punch — cannot determine IN/OUT; marked Absent per policy")),
		)

	if first_punch == last_punch:
		return _("Absent (Single Punch)"), _join(_("Duplicate/same-time punch only"))

	if late_mark:
		return (
			_("Present (Late)"),
			_join(
				_("Both punches present; late after {0}-minute grace").format(grace_minutes)
			),
		)

	return _("Present"), _join(_("First punch = IN, last punch = OUT"))


def _load_shift_cache():
	cache = {}
	for row in frappe.get_all("Shift Type", fields=["name", "start_time", "end_time"]):
		cache[row.name] = row
	return cache


def _load_shift_assignments(filters):
	"""Map (employee, date) -> shift_type from active Shift Assignment."""
	rows = frappe.db.sql(
		"""
		select employee, shift_type, start_date, end_date
		from `tabShift Assignment`
		where docstatus = 1
			and status = 'Active'
			and start_date <= %(to_date)s
			and ifnull(end_date, %(to_date)s) >= %(from_date)s
		""",
		{"from_date": filters.from_date, "to_date": filters.to_date},
		as_dict=True,
	)
	# Store list per employee for date lookup
	by_emp = defaultdict(list)
	for row in rows:
		by_emp[row.employee].append(row)
	return by_emp


def _load_approved_leaves(filters):
	rows = frappe.db.sql(
		"""
		select employee, from_date, to_date
		from `tabLeave Application`
		where docstatus = 1
			and status = 'Approved'
			and from_date <= %(to_date)s
			and to_date >= %(from_date)s
		""",
		{"from_date": filters.from_date, "to_date": filters.to_date},
		as_dict=True,
	)
	leave_days = set()
	for row in rows:
		day = getdate(row.from_date)
		end = getdate(row.to_date)
		while day <= end:
			leave_days.add((row.employee, day))
			day = add_days(day, 1)
	return leave_days


def _resolve_shift(
	employee,
	punch_date,
	checkin_shift,
	default_shift,
	assignment_cache,
	fallback_shift=None,
):
	"""Return (shift_name, source) where source is checkin|assignment|default|fallback|''."""
	if checkin_shift:
		return checkin_shift, "checkin"

	punch_date = getdate(punch_date)
	for row in assignment_cache.get(employee) or []:
		start = getdate(row.start_date)
		end = getdate(row.end_date) if row.end_date else punch_date
		if start <= punch_date <= end:
			return row.shift_type, "assignment"

	if default_shift:
		return default_shift, "default"

	if fallback_shift:
		return fallback_shift, "fallback"

	return "", ""


def _timedelta_to_time_str(value):
	if value is None:
		return None
	if isinstance(value, timedelta):
		total = int(value.total_seconds()) % (24 * 3600)
		hours = total // 3600
		minutes = (total % 3600) // 60
		seconds = total % 60
		return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
	return str(value)


def _get_shift_window(shift_name, punch_date, shift_cache):
	punch_date = getdate(punch_date)
	start_str = end_str = None

	meta = shift_cache.get(shift_name) if shift_name else None
	if meta:
		start_str = _timedelta_to_time_str(meta.start_time)
		end_str = _timedelta_to_time_str(meta.end_time)

	if not start_str and shift_name in SHIFT_TIMINGS:
		start_str, end_str = SHIFT_TIMINGS[shift_name]

	if not start_str:
		return None, None

	start_dt = get_datetime(f"{punch_date} {start_str}")
	end_dt = get_datetime(f"{punch_date} {end_str}") if end_str else None
	if end_dt and end_dt <= start_dt:
		# Overnight shift
		end_dt = end_dt + timedelta(days=1)
	return start_dt, end_dt


def get_chart_data(filters, data):
	if cint(filters.get("punch_log_view")):
		return _punch_volume_chart(filters)

	counts = defaultdict(int)
	for row in data or []:
		counts[row.get("policy_status") or _("Unknown")] += 1

	if not counts:
		return None

	# Fixed status order + colors so Present is always green and Absent is always red
	status_colors = {
		_("Present"): "#15803d",
		_("Present (Late)"): "#a16207",
		_("Present on Leave"): "#1d4ed8",
		_("Absent (Single Punch)"): "#b91c1c",
		_("Absent"): "#b91c1c",
	}
	preferred_order = [
		_("Present"),
		_("Present (Late)"),
		_("Present on Leave"),
		_("Absent (Single Punch)"),
		_("Absent"),
	]

	labels = [s for s in preferred_order if counts.get(s)]
	for status in counts:
		if status not in labels:
			labels.append(status)

	values = [counts[k] for k in labels]
	colors = [status_colors.get(k, "#64748B") for k in labels]

	return {
		"data": {
			"labels": labels,
			"datasets": [{"name": _("Days"), "values": values}],
		},
		"type": "percentage",
		"colors": colors,
		"title": _("Attendance by Policy Status"),
	}


def _punch_volume_chart(filters):
	conditions, values = get_checkin_conditions(filters)
	rows = frappe.db.sql(
		f"""
		select
			date(ec.time) as punch_date,
			sum(case when ec.log_type = 'IN' then 1 else 0 end) as in_count,
			sum(case when ec.log_type = 'OUT' then 1 else 0 end) as out_count
		from `tabEmployee Checkin` ec
		left join `tabEmployee` emp on emp.name = ec.employee
		where {conditions}
		group by date(ec.time)
		order by punch_date
		""",
		values,
		as_dict=True,
	)
	if not rows:
		return None

	return {
		"data": {
			"labels": [formatdate(r.punch_date, "dd MMM") for r in rows],
			"datasets": [
				{"name": _("IN"), "values": [cint(r.in_count) for r in rows]},
				{"name": _("OUT"), "values": [cint(r.out_count) for r in rows]},
			],
		},
		"type": "bar",
		"title": _("Check-ins by Day"),
		"colors": ["#449CF0", "#64748B"],
		"barOptions": {"stacked": 1, "spaceRatio": 0.45},
	}


def get_report_summary(filters, data):
	if cint(filters.get("punch_log_view")):
		conditions, values = get_checkin_conditions(filters)
		stats = frappe.db.sql(
			f"""
			select
				count(*) as total_punches,
				count(distinct ec.employee) as employees,
				sum(case when ec.log_type = 'IN' then 1 else 0 end) as in_count,
				sum(case when ec.log_type = 'OUT' then 1 else 0 end) as out_count
			from `tabEmployee Checkin` ec
			left join `tabEmployee` emp on emp.name = ec.employee
			where {conditions}
			""",
			values,
			as_dict=True,
		)[0]
		return [
			{"value": stats.total_punches or 0, "label": _("Total Punches"), "datatype": "Int", "indicator": "blue"},
			{"value": stats.employees or 0, "label": _("Employees"), "datatype": "Int", "indicator": "green"},
			{"value": stats.in_count or 0, "label": _("IN"), "datatype": "Int", "indicator": "green"},
			{"value": stats.out_count or 0, "label": _("OUT"), "datatype": "Int", "indicator": "orange"},
		]

	present = late = single = leave = 0
	for row in data or []:
		status = row.get("policy_status") or ""
		if status == _("Present on Leave"):
			leave += 1
		elif status == _("Present (Late)"):
			late += 1
			present += 1
		elif status == _("Present"):
			present += 1
		elif "Absent" in status:
			single += 1

	return [
		{"value": present, "label": _("Present Days"), "datatype": "Int", "indicator": "green"},
		{"value": late, "label": _("Late Marks"), "datatype": "Int", "indicator": "orange"},
		{"value": single, "label": _("Single Punch / Absent"), "datatype": "Int", "indicator": "red"},
		{"value": leave, "label": _("Present on Leave"), "datatype": "Int", "indicator": "blue"},
	]
