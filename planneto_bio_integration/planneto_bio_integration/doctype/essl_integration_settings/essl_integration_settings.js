// Copyright (c) 2026, Administrator and contributors
// For license information, please see license.txt

frappe.ui.form.on("eSSL Integration Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Sync"), function () {
			if (frm.is_dirty()) {
				frm.save().then(() => frm.trigger("run_sync"));
			} else {
				frm.trigger("run_sync");
			}
		});

		frm.add_custom_button(__("Test Connection"), function () {
			if (frm.is_dirty()) {
				frm.save().then(() => frm.trigger("run_test_connection"));
			} else {
				frm.trigger("run_test_connection");
			}
		});

		frm.add_custom_button(__("Link Raw Punches"), function () {
			frappe.call({
				method: "link_raw_punches",
				doc: frm.doc,
				freeze: true,
				freeze_message: __("Linking raw punches to employees..."),
				callback: function (r) {
					if (!r.exc) {
						let payload = r.message || {};
						frappe.msgprint({
							title: __("Link Raw Punches"),
							indicator: "green",
							message: payload.message || __("Linking completed."),
						});
						frm.refresh();
					}
				},
			});
		});
	},

	run_sync(frm) {
		frappe.call({
			method: "sync_punches",
			doc: frm.doc,
			freeze: true,
			freeze_message: __("Syncing punches from eSSL server..."),
			callback: function (r) {
				if (!r.exc) {
					let payload = r.message || {};
					let message = payload.message || __("Sync completed.");
					let has_errors = payload.errors && payload.errors.length;
					frappe.msgprint({
						title: has_errors ? __("Sync Failed") : __("Sync Completed"),
						indicator: has_errors ? "red" : "green",
						message: message,
					});
					frm.refresh();
				}
			},
		});
	},

	run_test_connection(frm) {
		frappe.call({
			method: "test_connection",
			doc: frm.doc,
			freeze: true,
			freeze_message: __("Testing eSSL connection..."),
			callback: function (r) {
				if (!r.exc) {
					let payload = r.message || {};
					frappe.msgprint({
						title: __("Test Connection"),
						indicator: "green",
						message: payload.message || __("Connection successful."),
					});
				}
			},
		});
	},
});
