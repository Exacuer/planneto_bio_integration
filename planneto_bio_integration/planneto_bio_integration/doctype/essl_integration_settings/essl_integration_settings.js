// Copyright (c) 2026, Administrator and contributors
// For license information, please see license.txt

frappe.ui.form.on("eSSL Integration Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Sync"), function () {
			if (frm.is_dirty()) {
				frm.save().then(() => {
					frm.trigger("run_sync");
				});
			} else {
				frm.trigger("run_sync");
			}
		}).addClass("btn-primary");
	},

	run_sync(frm) {
		frappe.call({
			method: "sync_punches",
			doc: frm.doc,
			freeze: true,
			freeze_message: __("Syncing punches from eSSL server..."),
			callback: function (r) {
				if (!r.exc) {
					let message = (r.message && r.message.message) || r.message || __("Sync completed successfully.");
					frappe.msgprint({
						title: __("Sync Completed"),
						indicator: "green",
						message: message
					});
					frm.refresh();
				}
			}
		});
	}
});

