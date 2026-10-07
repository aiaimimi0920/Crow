pub fn validate_config(raw: &str) -> Result<(), String> {
    let config: serde_json::Value = serde_json::from_str(raw).map_err(|error| error.to_string())?;
    let Some(dist) = config
        .get("build")
        .and_then(|build| {
            build
                .get("frontendDist")
                .or_else(|| build.get("frontend-dist"))
        })
        .and_then(serde_json::Value::as_str)
    else {
        return Ok(());
    };
    let bytes = dist.as_bytes();
    // Tauri 优先把字符串解析成 URL；Windows 盘符会使前端资源不再嵌入 EXE。
    if bytes.len() >= 2 && bytes[0].is_ascii_alphabetic() && bytes[1] == b':' {
        return Err(
            "Crow frontendDist must use a relative path, not a Windows drive URL; otherwise frontend assets are not embedded"
                .into(),
        );
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::validate_config;

    #[test]
    fn rejects_windows_drive_strings_before_tauri_treats_them_as_urls() {
        for path in [
            "C:/scratch/frontend",
            "C:\\scratch\\frontend",
            "z:/frontend",
            "C:frontend",
        ] {
            for key in ["frontendDist", "frontend-dist"] {
                let config = serde_json::json!({"build": {key: path}});
                let error = validate_config(&config.to_string()).unwrap_err();
                assert!(error.contains("frontend assets are not embedded"));
            }
        }
    }

    #[test]
    fn preserves_unambiguous_embedded_paths_and_other_overrides() {
        for config in [
            serde_json::json!({"build": {"frontendDist": "../dist"}}),
            serde_json::json!({"build": {"frontendDist": "../../../scratch/frontend"}}),
            serde_json::json!({"build": {"frontendDist": "/tmp/frontend"}}),
            serde_json::json!({"build": {"frontendDist": ["C:/scratch/index.html"]}}),
            serde_json::json!({"build": {"beforeBuildCommand": "npm run build"}}),
        ] {
            assert!(validate_config(&config.to_string()).is_ok());
        }
    }

    #[test]
    fn malformed_config_is_not_ignored() {
        assert!(validate_config("not json").is_err());
    }
}
