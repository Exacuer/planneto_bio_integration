# Copyright (c) 2026, Administrator and contributors
# For license information, please see license.txt

"""Worker Attendance Report — same policy view as Employee Checkin Report NEW,
with shift allocated from the worker's first check-in time.

Shift allocation (±30 minutes of shift start by default):
- FIRST SHIFT  (07:00) → check-in 06:30–07:30
- SECOND SHIFT (15:30) → check-in 15:00–16:00
- THIRD SHIFT  (00:00) → check-in 23:30–00:30
- DAY SHIFT    (08:00) → check-in 07:30–08:30
- NIGHT SHIFT  (20:00) → check-in 19:30–20:30
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

DEFAULT_CHECKIN_WINDOW_MINUTES = 30
# Standard duty for overtime: minutes beyond 8 hours 30 minutes (first → last punch)
STANDARD_WORK_MINUTES = 8 * 60 + 30

# Plant shift timings (HH:MM:SS) — start / end
SHIFT_TIMINGS = {
	"GENERAL SHIFT (A)": ("08:30:00", "17:45:00"),
	"GENERAL SHIFT (B)": ("08:30:00", "17:00:00"),
	"FIRST SHIFT": ("07:00:00", "15:30:00"),
	"SECOND SHIFT": ("15:30:00", "00:00:00"),
	"THIRD SHIFT": ("00:00:00", "07:00:00"),
	"DAY SHIFT": ("08:00:00", "20:00:00"),
	"NIGHT SHIFT": ("20:00:00", "08:00:00"),
}

# Shifts allocated from first check-in (± window around start). Order matters for ties.
CHECKIN_ALLOCATED_SHIFTS = (
	"FIRST SHIFT",
	"DAY SHIFT",
	"SECOND SHIFT",
	"NIGHT SHIFT",
	"THIRD SHIFT",
)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	validate_filters(filters)

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
		{"label": _("Allocated Shift"), "fieldname": "shift", "fieldtype": "Data", "width": 140},
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
		{"label": _("Allocated Shift"), "fieldname": "shift", "fieldtype": "Data", "width": 140},
		{"label": _("Shift Source"), "fieldname": "shift_source", "fieldtype": "Data", "width": 120},
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
		{"label": _("Overtime (Mins)"), "fieldname": "overtime_mins", "fieldtype": "Int", "width": 120},
		{
			"label": _("Overtime (Hours)"),
			"fieldname": "overtime_hours",
			"fieldtype": "Float",
			"width": 120,
			"precision": 2,
		},
		{"label": _("Late By (Mins)"), "fieldname": "late_by_mins", "fieldtype": "Int", "width": 110},
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

	by_day = defaultdict(list)
	for row in rows:
		by_day[(row.punch_date, row.employee)].append(row)

	for day_rows in by_day.values():
		day_rows.sort(key=lambda r: get_datetime(r.time))
		first_punch = get_datetime(day_rows[0].time)
		allocated_shift, _source = allocate_shift_from_checkin(first_punch)

		for idx, row in enumerate(day_rows):
			row.shift = allocated_shift
			if len(day_rows) == 1:
				row.punch_role = _("Single Punch")
			elif idx == 0:
				row.punch_role = _("IN (First)")
			elif idx == len(day_rows) - 1:
				row.punch_role = _("OUT (Last)")
			else:
				row.punch_role = _("Intermediate")

	if filters.get("shift"):
		rows = [r for r in rows if r.shift == filters.shift]

	rows.sort(key=lambda r: get_datetime(r.time), reverse=True)
	return rows


def get_summary_data(filters):
	detail_filters = frappe._dict({**filters, "log_type": None, "shift": None})
	detail_rows = get_detail_data(detail_filters)

	shift_cache = _load_shift_cache()
	leave_cache = _load_approved_leaves(filters)

	grouped = defaultdict(list)
	for row in detail_rows:
		grouped[(getdate(row.punch_date), row.employee)].append(row)

	provisional = []
	for (punch_date, employee), punches in grouped.items():
		punches = sorted(punches, key=lambda d: get_datetime(d.time))
		first = punches[0]
		all_times = [get_datetime(p.time) for p in punches]
		first_punch = all_times[0]
		last_punch = all_times[-1]
		total_punches = len(punches)

		shift_name, shift_source = allocate_shift_from_checkin(first_punch)
		shift_start, shift_end = _get_shift_window(shift_name, punch_date, shift_cache)

		hours_worked = 0.0
		overtime_mins = 0
		overtime_hours = 0.0
		if total_punches >= 2 and last_punch > first_punch:
			hours_worked = round(time_diff_in_hours(last_punch, first_punch), 2)
			worked_mins = cint(time_diff_in_seconds(last_punch, first_punch) / 60)
			if worked_mins > STANDARD_WORK_MINUTES:
				overtime_mins = worked_mins - STANDARD_WORK_MINUTES
				overtime_hours = round(overtime_mins / 60.0, 2)

		# Late By (Mins): any punch after shift start counts (including 1 minute late)
		late_by_mins = 0
		late_mark = _("No")
		if shift_start and first_punch > shift_start:
			late_seconds = time_diff_in_seconds(first_punch, shift_start)
			late_by_mins = max(1, cint(late_seconds / 60))
			if total_punches >= 2:
				late_mark = _("Yes")

		on_leave = (employee, punch_date) in leave_cache
		policy_status, remarks = _evaluate_policy_status(
			total_punches=total_punches,
			first_punch=first_punch,
			last_punch=last_punch,
			late_mark=late_mark == _("Yes"),
			on_leave=on_leave,
			punch_date=punch_date,
			shift_source=shift_source,
			has_shift_window=bool(shift_start),
		)

		if filters.get("shift") and shift_name != filters.shift:
			continue
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
				"shift_source": _shift_source_label(shift_source),
				"shift_start": shift_start.time() if shift_start else None,
				"first_in": first_punch.time() if first_punch else None,
				"last_out": last_punch.time() if total_punches >= 2 else None,
				"total_punches": total_punches,
				"hours_worked": hours_worked,
				"overtime_mins": overtime_mins,
				"overtime_hours": overtime_hours,
				"late_by_mins": late_by_mins,
				"policy_status": policy_status,
				"remarks": remarks,
			}
		)

	provisional.sort(
		key=lambda d: (d["punch_date"] or getdate(), d["employee"] or ""),
		reverse=True,
	)
	return provisional


def allocate_shift_from_checkin(first_punch):
	"""Allocate shift from first punch time within ±30 minutes of shift start.

	When two windows both match (e.g. 07:30 → FIRST and DAY), the closer start wins;
	ties keep the earlier entry in CHECKIN_ALLOCATED_SHIFTS (FIRST before DAY).
	"""
	if not first_punch:
		return "", "unallocated"

	first_punch = get_datetime(first_punch)
	punch_date = getdate(first_punch)
	window = timedelta(minutes=DEFAULT_CHECKIN_WINDOW_MINUTES)

	best_shift = ""
	best_delta = None

	for shift_name in CHECKIN_ALLOCATED_SHIFTS:
		start_str, _end_str = SHIFT_TIMINGS[shift_name]
		# Candidate start on punch date, and previous day (for midnight / overnight starts)
		for day_offset in (0, -1, 1):
			candidate_date = add_days(punch_date, day_offset)
			shift_start = get_datetime(f"{candidate_date} {start_str}")
			delta = abs(first_punch - shift_start)
			if delta <= window and (best_delta is None or delta < best_delta):
				best_delta = delta
				best_shift = shift_name

	if best_shift:
		return best_shift, "checkin_window"

	return "", "unallocated"


def _shift_source_label(source):
	labels = {
		"checkin_window": _("Check-in Window"),
		"unallocated": _("Unallocated"),
	}
	return labels.get(source, source or _("Unallocated"))


def _evaluate_policy_status(
	total_punches,
	first_punch,
	last_punch,
	late_mark,
	on_leave,
	punch_date,
	shift_source="",
	has_shift_window=False,
):
	notes = []

	if on_leave:
		return _("Present on Leave"), _("Approved leave — treated as Present on Leave")

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

	if shift_source == "checkin_window":
		notes.append(
			_("Shift allocated from first check-in (±{0} min of shift start)").format(
				DEFAULT_CHECKIN_WINDOW_MINUTES
			)
		)
	elif not has_shift_window:
		notes.append(
			_("Check-in outside shift windows (±{0} min) — shift not allocated").format(
				DEFAULT_CHECKIN_WINDOW_MINUTES
			)
		)

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
			_join(_("Both punches present; first punch after shift start")),
		)

	return _("Present"), _join(_("First punch = IN, last punch = OUT"))


def _load_shift_cache():
	cache = {}
	for row in frappe.get_all("Shift Type", fields=["name", "start_time", "end_time"]):
		cache[row.name] = row
	return cache


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
	total_overtime_mins = 0
	total_overtime_hours = 0.0
	shift_counts = defaultdict(int)
	for row in data or []:
		status = row.get("policy_status") or ""
		if row.get("shift"):
			shift_counts[row["shift"]] += 1
		total_overtime_mins += cint(row.get("overtime_mins") or 0)
		total_overtime_hours += float(row.get("overtime_hours") or 0)
		if status == _("Present on Leave"):
			leave += 1
		elif status == _("Present (Late)"):
			late += 1
			present += 1
		elif status == _("Present"):
			present += 1
		elif "Absent" in status:
			single += 1

	summary = [
		{"value": present, "label": _("Present Days"), "datatype": "Int", "indicator": "green"},
		{"value": late, "label": _("Late Marks"), "datatype": "Int", "indicator": "orange"},
		{"value": single, "label": _("Single Punch / Absent"), "datatype": "Int", "indicator": "red"},
		{"value": leave, "label": _("Present on Leave"), "datatype": "Int", "indicator": "blue"},
		{
			"value": total_overtime_mins,
			"label": _("Overtime (Mins)"),
			"datatype": "Int",
			"indicator": "blue",
		},
		{
			"value": round(total_overtime_hours, 2),
			"label": _("Overtime (Hours)"),
			"datatype": "Float",
			"indicator": "blue",
		},
	]

	# Top allocated shifts for quick view
	for shift_name, count in sorted(shift_counts.items(), key=lambda x: (-x[1], x[0]))[:3]:
		summary.append(
			{"value": count, "label": shift_name, "datatype": "Int", "indicator": "gray"}
		)

	return summary
