app_name = "planneto_bio_integration"
app_title = "Planneto Bio Integration"
app_publisher = "Administrator"
app_description = "eSSL Biometric Integration for Planetto"
app_email = "admin@example.com"
app_license = "mit"

required_apps = ["hrms"]

export_python_type_annotations = True

scheduler_events = {
	"all": [
		"planneto_bio_integration.planneto_bio_integration.doctype.essl_integration_settings.essl_integration_settings.auto_sync_essl_punches"
	]
}
