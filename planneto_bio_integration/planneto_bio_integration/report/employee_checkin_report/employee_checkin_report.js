// Copyright (c) 2026, Administrator and contributors
// For license information, please see license.txt

frappe.query_reports["Employee Checkin Report"] = {
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
			fieldname: "branch",
			label: __("Branch"),
			fieldtype: "Link",
			options: "Branch",
		},
		{
			fieldname: "log_type",
			label: __("Log Type"),
			fieldtype: "Select",
			options: "\nIN\nOUT",
		},
		{
			fieldname: "group_by_employee",
			label: __("Daily Summary by Employee"),
			fieldtype: "Check",
			default: 0,
		},
	],
	formatter: (value, row, column, data, default_formatter) => {
		value = default_formatter(value, row, column, data);
		if (!data) {
			return value;
		}

		if (column.fieldname === "log_type") {
			if (data.log_type === "IN") {
				value = `<span style="color:#0f766e;font-weight:600">${value}</span>`;
			} else if (data.log_type === "OUT") {
				value = `<span style="color:#b45309;font-weight:600">${value}</span>`;
			}
		}

		if (column.fieldname === "attendance_status") {
			if (data.attendance_status === "Present") {
				value = `<span style="color:#15803d;font-weight:600">${value}</span>`;
			} else if (data.attendance_status === "Absent") {
				value = `<span style="color:#b91c1c;font-weight:600">${value}</span>`;
			} else if (data.attendance_status === "Half Day") {
				value = `<span style="color:#a16207;font-weight:600">${value}</span>`;
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
