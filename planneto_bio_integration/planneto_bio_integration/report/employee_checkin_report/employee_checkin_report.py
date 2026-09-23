# Copyright (c) 2026, Administrator and contributors
# For license information, please see license.txt

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import add_days, cint, formatdate, get_datetime, getdate, time_diff_in_hours


def execute(filters=None):
	filters = frappe._dict(filters or {})
	validate_filters(filters)

	if filters.get("group_by_employee"):
		columns = get_summary_columns()
		data = get_summary_data(filters)
	else:
		columns = get_detail_columns()
		data = get_detail_data(filters)

	chart = get_chart_data(filters)
	report_summary = get_report_summary(filters)

	return columns, data, None, chart, report_summary


def validate_filters(filters):
	if not filters.get("from_date") or not filters.get("to_date"):
		frappe.throw(_("From Date and To Date are required"))

	if getdate(filters.from_date) > getdate(filters.to_date):
		frappe.throw(_("From Date cannot be after To Date"))


def get_detail_columns():
	return [
		{
			"label": _("Date"),
			"fieldname": "punch_date",
			"fieldtype": "Date",
			"width": 110,
		},
		{
			"label": _("Employee"),
			"fieldname": "employee",
			"fieldtype": "Link",
			"options": "Employee",
			"width": 120,
		},
		{
			"label": _("Employee Name"),
			"fieldname": "employee_name",
			"fieldtype": "Data",
			"width": 180,
		},
		{
			"label": _("Department"),
			"fieldname": "department",
			"fieldtype": "Link",
			"options": "Department",
			"width": 150,
		},
		{
			"label": _("Designation"),
			"fieldname": "designation",
			"fieldtype": "Link",
			"options": "Designation",
			"width": 140,
		},
		{
			"label": _("Branch"),
			"fieldname": "branch",
			"fieldtype": "Link",
			"options": "Branch",
			"width": 120,
		},
		{
			"label": _("Log Type"),
			"fieldname": "log_type",
			"fieldtype": "Data",
			"width": 90,
		},
		{
			"label": _("Punch Time"),
			"fieldname": "time",
			"fieldtype": "Datetime",
			"width": 160,
		},
		{
			"label": _("Shift"),
			"fieldname": "shift",
			"fieldtype": "Link",
			"options": "Shift Type",
			"width": 120,
		},
		{
			"label": _("Attendance"),
			"fieldname": "attendance",
			"fieldtype": "Link",
			"options": "Attendance",
			"width": 140,
		},
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
		{
			"label": _("Date"),
			"fieldname": "punch_date",
			"fieldtype": "Date",
			"width": 110,
		},
		{
			"label": _("Employee"),
			"fieldname": "employee",
			"fieldtype": "Link",
			"options": "Employee",
			"width": 120,
		},
		{
			"label": _("Employee Name"),
			"fieldname": "employee_name",
			"fieldtype": "Data",
			"width": 180,
		},
		{
			"label": _("Department"),
			"fieldname": "department",
			"fieldtype": "Link",
			"options": "Department",
			"width": 150,
		},
		{
			"label": _("First IN"),
			"fieldname": "first_in",
			"fieldtype": "Datetime",
			"width": 160,
		},
		{
			"label": _("Last OUT"),
			"fieldname": "last_out",
			"fieldtype": "Datetime",
			"width": 160,
		},
		{
			"label": _("Total Punches"),
			"fieldname": "total_punches",
			"fieldtype": "Int",
			"width": 120,
		},
		{
			"label": _("IN Count"),
			"fieldname": "in_count",
			"fieldtype": "Int",
			"width": 100,
		},
		{
			"label": _("OUT Count"),
			"fieldname": "out_count",
			"fieldtype": "Int",
			"width": 100,
		},
		{
			"label": _("Hours Worked"),
			"fieldname": "hours_worked",
			"fieldtype": "Float",
			"width": 120,
			"precision": 2,
		},
		{
			"label": _("Attendance"),
			"fieldname": "attendance_status",
			"fieldtype": "Data",
			"width": 120,
		},
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

	if filters.get("branch"):
		conditions.append("emp.branch = %(branch)s")
		values["branch"] = filters.branch

	return " and ".join(conditions), values


def get_detail_data(filters):
	conditions, values = get_checkin_conditions(filters)
	rows = frappe.db.sql(
		f"""
		select
			date(ec.time) as punch_date,
			ec.employee,
			ec.employee_name,
			emp.department,
			emp.designation,
			emp.branch,
			ec.log_type,
			ec.time,
			ec.shift,
			ec.attendance,
			ec.name
		from `tabEmployee Checkin` ec
		left join `tabEmployee` emp on emp.name = ec.employee
		where {conditions}
		order by ec.time desc, ec.employee
		""",
		values,
		as_dict=True,
	)
	return rows


def get_summary_data(filters):
	detail_rows = get_detail_data(
		frappe._dict({**filters, "log_type": None, "group_by_employee": 0})
	)

	grouped = defaultdict(list)
	for row in detail_rows:
		key = (row.punch_date, row.employee)
		grouped[key].append(row)

	summary = []
	for (punch_date, employee), punches in grouped.items():
		punches = sorted(punches, key=lambda d: get_datetime(d.time))
		first = punches[0]
		in_times = [get_datetime(p.time) for p in punches if p.log_type == "IN"]
		out_times = [get_datetime(p.time) for p in punches if p.log_type == "OUT"]

		first_in = min(in_times) if in_times else None
		last_out = max(out_times) if out_times else None
		hours_worked = 0.0
		if first_in and last_out and last_out > first_in:
			hours_worked = round(time_diff_in_hours(last_out, first_in), 2)

		attendance_status = None
		if first.attendance:
			attendance_status = frappe.db.get_value("Attendance", first.attendance, "status")

		summary.append(
			{
				"punch_date": punch_date,
				"employee": employee,
				"employee_name": first.employee_name,
				"department": first.department,
				"first_in": first_in,
				"last_out": last_out,
				"total_punches": len(punches),
				"in_count": len(in_times),
				"out_count": len(out_times),
				"hours_worked": hours_worked,
				"attendance_status": attendance_status or "",
			}
		)

	summary.sort(key=lambda d: (d["punch_date"] or getdate(), d["employee"] or ""), reverse=True)
	return summary


def get_chart_data(filters):
	conditions, values = get_checkin_conditions(filters)
	same_day = getdate(filters.from_date) == getdate(filters.to_date)

	if same_day:
		rows = frappe.db.sql(
			f"""
			select
				hour(ec.time) as bucket,
				sum(case when ec.log_type = 'IN' then 1 else 0 end) as in_count,
				sum(case when ec.log_type = 'OUT' then 1 else 0 end) as out_count
			from `tabEmployee Checkin` ec
			left join `tabEmployee` emp on emp.name = ec.employee
			where {conditions}
			group by hour(ec.time)
			order by bucket
			""",
			values,
			as_dict=True,
		)
		if not rows:
			return None

		# Continuous 24h axis between first and last punch hour
		by_hour = {cint(r.bucket): r for r in rows}
		start_h = min(by_hour)
		end_h = max(by_hour)
		labels = []
		in_values = []
		out_values = []
		for hour in range(start_h, end_h + 1):
			labels.append(f"{hour:02d}:00")
			row = by_hour.get(hour)
			in_values.append(cint(row.in_count) if row else 0)
			out_values.append(cint(row.out_count) if row else 0)
		title = _("Check-ins by Hour")
	else:
		rows = frappe.db.sql(
			f"""
			select
				date(ec.time) as bucket,
				sum(case when ec.log_type = 'IN' then 1 else 0 end) as in_count,
				sum(case when ec.log_type = 'OUT' then 1 else 0 end) as out_count
			from `tabEmployee Checkin` ec
			left join `tabEmployee` emp on emp.name = ec.employee
			where {conditions}
			group by date(ec.time)
			order by bucket
			""",
			values,
			as_dict=True,
		)
		if not rows:
			return None

		by_date = {getdate(r.bucket): r for r in rows}
		labels = []
		in_values = []
		out_values = []
		day = getdate(filters.from_date)
		end = getdate(filters.to_date)
		# Cap continuous axis at 45 days to keep the chart readable
		span_days = (end - day).days + 1
		if span_days > 45:
			for row in rows:
				labels.append(formatdate(row.bucket, "dd MMM"))
				in_values.append(cint(row.in_count))
				out_values.append(cint(row.out_count))
		else:
			while day <= end:
				labels.append(formatdate(day, "dd MMM"))
				row = by_date.get(day)
				in_values.append(cint(row.in_count) if row else 0)
				out_values.append(cint(row.out_count) if row else 0)
				day = add_days(day, 1)
		title = _("Check-ins by Day")

	return {
		"data": {
			"labels": labels,
			"datasets": [
				{"name": _("IN"), "values": in_values},
				{"name": _("OUT"), "values": out_values},
			],
		},
		"type": "bar",
		"title": title,
		"colors": ["#449CF0", "#64748B"],
		"barOptions": {
			"stacked": 1,
			"spaceRatio": 0.45,
		},
		"axisOptions": {
			"xIsSeries": 1,
			"shortenYAxisNumbers": 1,
		},
	}


def get_report_summary(filters):
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
		{
			"value": stats.total_punches or 0,
			"label": _("Total Punches"),
			"datatype": "Int",
			"indicator": "blue",
		},
		{
			"value": stats.employees or 0,
			"label": _("Employees"),
			"datatype": "Int",
			"indicator": "green",
		},
		{
			"value": stats.in_count or 0,
			"label": _("IN"),
			"datatype": "Int",
			"indicator": "green",
		},
		{
			"value": stats.out_count or 0,
			"label": _("OUT"),
			"datatype": "Int",
			"indicator": "orange",
		},
	]
