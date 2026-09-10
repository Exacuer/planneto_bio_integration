# Planneto Bio Integration

**Planneto Bio Integration** is a custom Frappe application designed to seamlessly integrate eSSL Biometric attendance devices with Frappe Framework and HRMS (ERPNext). It enables central server configuration, device tracking, punch log synchronization, and manual sync capabilities.

---

## Features

- **Centralized Server Settings**: Manage eSSL web service Base URL, Username, and Password from a single settings page.
- **Biometric Device Registry**: Track multiple biometric devices with labels, serial numbers, enabled status, and last synced timestamps.
- **Raw Punch Logs**: Store and manage raw punch records (`attendance_device_id`, `punch_time`, `employee`, `device_serial`, `dedup_key`) to eliminate duplicate punches.
- **One-Click Manual Sync**: Trigger punch synchronization on-demand directly from the **eSSL Integration Settings** form via the **Sync** action button.

---

## Prerequisites

- **Frappe Framework**: `v15.0.0` or higher
- **HRMS App**: `v15.0.0` or higher
- **Python**: `>= 3.10`

---

## Installation Guide

### Option A: Local / Self-Hosted Bench Installation

1. **Fetch the App**:
   From your bench directory (e.g., `frappe-bench`), download the app:
   ```bash
   bench get-app https://github.com/<your-username>/planneto_bio_integration.git
   ```

2. **Install on Site**:
   Install the application onto your target site:
   ```bash
   bench --site <site-name> install-app planneto_bio_integration
   ```

3. **Run Migrations**:
   Ensure database schemas are up to date:
   ```bash
   bench --site <site-name> migrate
   ```

4. **Restart Bench**:
   ```bash
   bench restart
   ```

---

### Option B: Frappe Cloud Installation

1. Navigate to your **Frappe Cloud Dashboard** > **Benches** > Select your bench group.
2. Click **Apps** > **+ Add App** > **Public Repository** (or **Private Repository**).
3. Paste the repository URL: `https://github.com/<your-username>/planneto_bio_integration.git` and select your branch (e.g., `main`).
4. Click **Add App** and deploy the bench update.
5. In your site dashboard, click **Install App** and select **Planneto Bio Integration**.

---

## Configuration & Usage

### 1. Configure eSSL Server & Devices

1. Log in to Frappe Desk as a **System Manager**.
2. Search for **eSSL Integration Settings** in the awesomebar (`Ctrl + G`).
3. Fill in your eSSL server details:
   - **Base URL**: e.g., `http://192.168.1.100/ESSLService` or `http://43.241.31.104:85/iclock`
   - **Username**: Your eSSL server API username
   - **Password**: Your eSSL server API password
4. Under the **Devices** section, add your biometric devices:
   - **Device Label**: A friendly name (e.g., `Main Gate`, `Office HQ`)
   - **Serial Number**: The physical serial number of the device (e.g., `JNP2241600886`)
   - **Enabled**: Check to include this device in punch synchronization
5. Click **Save**.

### 2. Manual Punch Synchronization

- On the **eSSL Integration Settings** form, click the primary **Sync** button at the top right.
- The system will validate server configuration, update device synchronization timestamps, and report the results.

### 3. Viewing Synchronized Punches

- Search for **eSSL Raw Punch** in Frappe Desk to inspect synced punch logs.
- Each record links the `attendance_device_id` to the corresponding `Employee` and records the exact `punch_time` and `device_serial`.

---

## Included DocTypes

| DocType Name | Type | Description |
| :--- | :--- | :--- |
| **`eSSL Integration Settings`** | Single | Main configuration page for server credentials and registered devices. |
| **`eSSL Device`** | Child Table | Table row representing an individual eSSL biometric device. |
| **`eSSL Raw Punch`** | Standard | Log storing raw attendance punch timestamps fetched from biometric devices. |

---

## License

This project is licensed under the [MIT License](license.txt).
