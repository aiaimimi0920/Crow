use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

static ACTIVE: AtomicBool = AtomicBool::new(false);

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SettingsRequest {
    action: String,
    #[serde(default)]
    origin: String,
    #[serde(default)]
    body: Option<Value>,
}

struct Guard;
impl Drop for Guard {
    fn drop(&mut self) {
        ACTIVE.store(false, Ordering::Release);
    }
}

fn encode(request: &SettingsRequest) -> Result<Vec<u8>, String> {
    if !matches!(
        request.action.as_str(),
        "config"
            | "get"
            | "apply"
            | "restart_status"
            | "restart"
            | "start"
            | "pause"
            | "resume"
            | "manual_update"
            | "reanalyze"
            | "reset_links"
    ) {
        return Err("Unsupported settings action".into());
    }
    let raw = serde_json::to_vec(request).map_err(|_| "Invalid settings request")?;
    if raw.len() > 20000 {
        return Err("Settings request is too large".into());
    }
    Ok(raw)
}

fn execute(request: SettingsRequest) -> Result<Value, String> {
    let raw = encode(&request)?;
    if ACTIVE
        .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
        .is_err()
    {
        return Err("Settings operation is in progress".into());
    }
    let _guard = Guard;
    let script = super::bundled_script_path("desktop-auth-challenge.ps1")
        .ok_or("Desktop settings components are not installed")?;
    let root = std::path::Path::new(&script)
        .parent()
        .and_then(std::path::Path::parent)
        .ok_or("Invalid desktop bundle")?;
    let helper = root.join("tools").join("desktop_settings_client.py");
    if !helper.is_file() {
        return Err("Desktop settings helper is not installed".into());
    }
    let python = super::runtime_config::python_for_bundle(root)?
        .ok_or("Desktop Python interpreter is not configured")?;
    let mut command = Command::new(python);
    command
        .arg(&helper)
        .current_dir(root)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    #[cfg(windows)]
    command.creation_flags(0x08000000);
    let output = super::helper_process::run(&mut command, raw, std::time::Duration::from_secs(35))
        .map_err(|code| {
            eprintln!("Settings helper failed: {code}");
            format!("设置请求未完成（{code}）；请刷新状态确认，勿重复提交")
        })?;
    if !output.status.success() || output.stdout.len() > 65536 {
        eprintln!(
            "Settings helper exit={:?}, stderr_bytes={}",
            output.status.code(),
            output.stderr.len()
        );
        return Err("Settings helper returned an invalid response".into());
    }
    serde_json::from_slice(&output.stdout).map_err(|_| "Settings response is invalid".into())
}

#[tauri::command]
pub async fn desktop_settings_action(request: SettingsRequest) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || execute(request))
        .await
        .map_err(|_| "Settings background task failed")?
}

#[cfg(test)]
mod tests {
    use super::{encode, SettingsRequest};

    #[test]
    fn request_is_closed_and_never_becomes_command_arguments() {
        assert!(
            serde_json::from_str::<SettingsRequest>(r#"{"action":"get","token":"secret"}"#)
                .is_err()
        );
        let request = SettingsRequest {
            action: "shell".into(),
            origin: String::new(),
            body: None,
        };
        assert!(encode(&request).is_err());
    }

    #[test]
    #[ignore = "explicit read-only installed-bundle validation; never part of offline tests"]
    fn installed_bundle_read_only_probe() {
        assert_eq!(
            std::env::var("CROW_LIVE_CONTROL_READ_ONLY").as_deref(),
            Ok("1")
        );
        let configured = super::execute(SettingsRequest {
            action: "config".into(),
            origin: String::new(),
            body: None,
        })
        .unwrap();
        assert_eq!(configured["configured"], true);
        let response = super::execute(SettingsRequest {
            action: "get".into(),
            origin: configured["origin"].as_str().unwrap().into(),
            body: None,
        })
        .unwrap();
        assert_eq!(response["ok"], true);
        assert_eq!(response["available"], true);
        assert!(response["effective"].is_object());
    }
}
