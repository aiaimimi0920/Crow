mod auth_bridge;
mod desktop_tray;
mod environment_aliases;
mod helper_process;
mod runtime_config;
mod settings_bridge;

#[cfg(test)]
#[path = "../build_frontend.rs"]
mod build_frontend;

#[tauri::command]
fn default_api_base() -> Result<String, String> {
    let configured = environment_aliases::api_source(
        std::env::var("CROW_COLLECTOR_API_BASE").ok(),
        std::env::var("FAPAI_COLLECTOR_API_BASE").ok(),
        || match bundled_script_path("desktop-auth-challenge.ps1") {
            Some(script) => runtime_config::api_base_for_script(std::path::Path::new(&script)),
            None => Ok(None),
        },
    )?;
    Ok(api_base_or_default(configured))
}

fn api_base_or_default(value: Option<String>) -> String {
    value
        .filter(|value| !value.trim().is_empty())
        .unwrap_or_else(|| "http://127.0.0.1:8001".to_string())
}

#[cfg(test)]
mod api_base_tests {
    use super::api_base_or_default;

    #[test]
    fn defaults_to_loopback_and_keeps_explicit_override() {
        assert_eq!(api_base_or_default(None), "http://127.0.0.1:8001");
        assert_eq!(
            api_base_or_default(Some("  ".into())),
            "http://127.0.0.1:8001"
        );
        assert_eq!(
            api_base_or_default(Some("http://localhost:9000".into())),
            "http://localhost:9000"
        );
    }
}

fn bundled_script_path(script_name: &str) -> Option<String> {
    if let Ok(current_exe) = std::env::current_exe() {
        if let Some(parent) = current_exe.parent() {
            let candidate = parent.join("scripts").join(script_name);
            if candidate.exists() {
                return Some(candidate.to_string_lossy().to_string());
            }
        }
    }

    #[cfg(debug_assertions)]
    if let Ok(current_dir) = std::env::current_dir() {
        for root in current_dir.ancestors() {
            let candidate = root.join("scripts").join(script_name);
            if candidate.exists() {
                return Some(candidate.to_string_lossy().to_string());
            }
        }
    }
    None
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| desktop_tray::install(app))
        .invoke_handler(tauri::generate_handler![
            default_api_base,
            auth_bridge::desktop_auth_action,
            settings_bridge::desktop_settings_action
        ])
        .run(tauri::generate_context!())
        .expect("error while running Crow collector desktop application");
}
