// Copyright (c) 2026, Administrator and contributors
// For license information, please see license.txt

frappe.query_reports["Worker Attendance Report"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.month_start(),
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.get_today(),
		},
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
		},
		{
			fieldname: "employee",
			label: __("Employee"),
			fieldtype: "Link",
			options: "Employee",
			get_query: () => ({
				filters: { status: "Active" },
			}),
		},
		{
			fieldname: "department",
			label: __("Department"),
			fieldtype: "Link",
			options: "Department",
		},
		{
			fieldname: "shift",
			label: __("Shift"),
			fieldtype: "Select",
			options: [
				"",
				"FIRST SHIFT",
				"SECOND SHIFT",
				"THIRD SHIFT",
				"DAY SHIFT",
				"NIGHT SHIFT",
				"GENERAL SHIFT (A)",
				"GENERAL SHIFT (B)",
			].join("\n"),
			description: __(
				"Filter by shift allocated from first check-in (±30 min of shift start)"
			),
		},
		{
			fieldname: "policy_status",
			label: __("Policy Status"),
			fieldtype: "Select",
			options: [
				"",
				"Present",
				"Present (Late)",
				"Absent (Single Punch)",
				"Absent",
				"Present on Leave",
			].join("\n"),
		},
		{
			fieldname: "late_only",
			label: __("Late Marks Only"),
			fieldtype: "Check",
			default: 0,
		},
		{
			fieldname: "punch_log_view",
			label: __("Raw Punch Log View"),
			fieldtype: "Check",
			default: 0,
		},
		{
			fieldname: "log_type",
			label: __("Log Type"),
			fieldtype: "Select",
			options: "\nIN\nOUT",
			depends_on: "punch_log_view",
		},
	],
	formatter: (value, row, column, data, default_formatter) => {
		value = default_formatter(value, row, column, data);
		if (!data) {
			return value;
		}

		if (column.fieldname === "log_type" || column.fieldname === "punch_role") {
			const text = data.punch_role || data.log_type || "";
			if (String(text).includes("IN")) {
				value = `<span style="color:#0f766e;font-weight:600">${value}</span>`;
			} else if (String(text).includes("OUT")) {
				value = `<span style="color:#b45309;font-weight:600">${value}</span>`;
			} else if (String(text).includes("Single")) {
				value = `<span style="color:#b91c1c;font-weight:600">${value}</span>`;
			}
		}

		if (column.fieldname === "policy_status") {
			const status = data.policy_status || "";
			if (status === "Present") {
				value = `<span style="color:#15803d;font-weight:600">${value}</span>`;
			} else if (status === "Present (Late)") {
				value = `<span style="color:#a16207;font-weight:600">${value}</span>`;
			} else if (status.includes("Absent")) {
				value = `<span style="color:#b91c1c;font-weight:600">${value}</span>`;
			} else if (status === "Present on Leave") {
				value = `<span style="color:#1d4ed8;font-weight:600">${value}</span>`;
			}
		}

		if (column.fieldname === "late_by_mins" && data.late_by_mins > 0) {
			value = `<span style="color:#b45309;font-weight:600">${value}</span>`;
		}

		if (
			(column.fieldname === "overtime_mins" && data.overtime_mins > 0) ||
			(column.fieldname === "overtime_hours" && data.overtime_hours > 0)
		) {
			value = `<span style="color:#1d4ed8;font-weight:600">${value}</span>`;
		}

		if (column.fieldname === "shift_source") {
			if (data.shift_source === "checkin_window") {
				value = `<span style="color:#0f766e;font-weight:600">${value}</span>`;
			} else if (!data.shift_source || data.shift_source === "unallocated") {
				value = `<span style="color:#b91c1c;font-weight:600">${value || __("Unallocated")}</span>`;
			}
		}

		return value;
	},
	onload(report) {
		const render_chart = report.render_chart.bind(report);
		report.render_chart = (options) => {
			if (options) {
				options.height = 300;
				options.valuesOverPoints = 0;
				options.tooltipOptions = {
					formatTooltipY: (d) => (d == null ? "0" : String(d)),
				};
			}
			render_chart(options);
		};
	},
};
