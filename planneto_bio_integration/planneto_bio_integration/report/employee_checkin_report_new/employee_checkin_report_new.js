// Copyright (c) 2026, Administrator and contributors
// For license information, please see license.txt

frappe.query_reports["Employee Checkin Report NEW"] = {
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
			fieldtype: "Link",
			options: "Shift Type",
		},
		{
			fieldname: "fallback_shift",
			label: __("Fallback Shift (if unassigned)"),
			fieldtype: "Link",
			options: "Shift Type",
			default: "GENERAL SHIFT (A)",
			description: __(
				"Used for late calculation when Employee Checkin / Shift Assignment / Default Shift is blank"
			),
		},
		{
			fieldname: "grace_minutes",
			label: __("Late Grace (Minutes)"),
			fieldtype: "Int",
			default: 15,
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

		if (column.fieldname === "late_mark") {
			if (data.late_mark === __("Yes") || data.late_mark === "Yes") {
				value = `<span style="color:#b45309;font-weight:600">${value}</span>`;
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
