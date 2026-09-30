use std::io::Read;
use std::path::Path;

fn parse_api_base(raw: &[u8]) -> Result<Option<String>, &'static str> {
    let Some(value) = parse_config(raw) else {
        return Ok(None);
    };
    let api = configured_alias(&value, "COLLECTOR_API_BASE", false)?;
    Ok(api.as_deref().and_then(validate_api_base))
}

fn configured_alias(
    value: &serde_json::Value,
    suffix: &str,
    path: bool,
) -> Result<Option<String>, &'static str> {
    let read = |prefix: &str| {
        value
            .get("environment")?
            .get(format!("{prefix}_{suffix}"))?
            .as_str()
            .map(str::to_owned)
    };
    super::environment_aliases::select(
        read("CROW"),
        read("FAPAI"),
        |left, right| {
            if path {
                super::environment_aliases::same_absolute_path(left, right)
            } else {
                left == right
            }
        },
        if path {
            super::environment_aliases::PYTHON_CONFLICT
        } else {
            super::environment_aliases::API_CONFLICT
        },
    )
}

fn parse_config(raw: &[u8]) -> Option<serde_json::Value> {
    if raw.len() > 16_384 {
        return None;
    }
    let value: serde_json::Value = serde_json::from_slice(raw).ok()?;
    if value.get("version")?.as_u64()? != 1 {
        return None;
    }
    Some(value)
}

pub fn validate_api_base(api: &str) -> Option<String> {
    if api.len() > 8192 || api.chars().any(char::is_control) {
        return None;
    }
    let api = api.trim();
    let url = tauri::Url::parse(api).ok()?;
    if !matches!(url.scheme(), "http" | "https")
        || !url.username().is_empty()
        || url.password().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
        || url.host_str().is_none()
        || !matches!(url.path(), "" | "/" | "/api" | "/api/")
    {
        return None;
    }
    Some(api.to_string())
}

fn read_config_file(path: &Path) -> Option<Vec<u8>> {
    let mut raw = Vec::new();
    std::fs::File::open(path)
        .ok()?
        .take(16_385)
        .read_to_end(&mut raw)
        .ok()?;
    Some(raw)
}

pub fn api_base_for_script(script: &Path) -> Result<Option<String>, &'static str> {
    let path = script
        .parent()
        .and_then(Path::parent)
        .map(|root| root.join("crow-desktop.runtime.json"));
    let Some(raw) = path.and_then(|path| read_config_file(&path)) else {
        return Ok(None);
    };
    parse_api_base(&raw)
}

pub fn python_for_bundle(root: &Path) -> Result<Option<std::path::PathBuf>, &'static str> {
    let Some(value) = read_config_file(&root.join("crow-desktop.runtime.json"))
        .and_then(|raw| parse_config(&raw))
    else {
        return Ok(None);
    };
    let Some(raw) = configured_alias(&value, "DESKTOP_PYTHON_PATH", true)? else {
        return Ok(None);
    };
    let path = std::path::PathBuf::from(raw);
    Ok((path.is_absolute() && path.is_file()).then_some(path))
}

#[cfg(test)]
mod tests {
    use super::parse_api_base;

    #[test]
    fn direct_launch_uses_the_same_configured_api_as_the_auth_helper() {
        let raw = br#"{"version":1,"environment":{"FAPAI_COLLECTOR_API_BASE":"https://nas.example.invalid/api"}}"#;
        assert_eq!(
            parse_api_base(raw).unwrap().as_deref(),
            Some("https://nas.example.invalid/api")
        );
        assert_eq!(parse_api_base(b"invalid"), Ok(None));
        assert_eq!(parse_api_base(&vec![b' '; 16_385]), Ok(None));
    }

    #[test]
    fn saved_api_accepts_both_names_and_rejects_conflicts() {
        for environment in [
            serde_json::json!({"CROW_COLLECTOR_API_BASE":"https://example.invalid/api"}),
            serde_json::json!({"FAPAI_COLLECTOR_API_BASE":"https://example.invalid/api"}),
            serde_json::json!({"CROW_COLLECTOR_API_BASE":"https://example.invalid/api", "FAPAI_COLLECTOR_API_BASE":"https://example.invalid/api"}),
        ] {
            let raw = serde_json::json!({"version":1,"environment":environment});
            assert_eq!(
                parse_api_base(raw.to_string().as_bytes())
                    .unwrap()
                    .as_deref(),
                Some("https://example.invalid/api")
            );
        }
        let raw = serde_json::json!({"version":1,"environment":{"CROW_COLLECTOR_API_BASE":"private-new", "FAPAI_COLLECTOR_API_BASE":"private-old"}});
        assert_eq!(
            parse_api_base(raw.to_string().as_bytes()),
            Err(crate::environment_aliases::API_CONFLICT)
        );
    }

    #[test]
    fn saved_interpreter_aliases_keep_existing_file_and_fail_before_execution() {
        let stamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root =
            std::env::temp_dir().join(format!("crow-runtime-test-{}-{stamp}", std::process::id()));
        std::fs::create_dir(&root).unwrap();
        let interpreter = root.join("synthetic-python");
        std::fs::write(&interpreter, b"fixture only, never execute").unwrap();
        let config = root.join("crow-desktop.runtime.json");
        for prefix in ["CROW", "FAPAI"] {
            let mut environment = serde_json::Map::new();
            environment.insert(
                format!("{prefix}_DESKTOP_PYTHON_PATH"),
                serde_json::json!(interpreter),
            );
            std::fs::write(
                &config,
                serde_json::json!({"version":1,"environment":environment}).to_string(),
            )
            .unwrap();
            assert_eq!(
                super::python_for_bundle(&root).unwrap(),
                Some(interpreter.clone())
            );
        }
        let equal = serde_json::json!({"version":1,"environment":{"CROW_DESKTOP_PYTHON_PATH":interpreter,"FAPAI_DESKTOP_PYTHON_PATH":root.join(".").join("synthetic-python")}});
        std::fs::write(&config, equal.to_string()).unwrap();
        assert_eq!(
            super::python_for_bundle(&root).unwrap(),
            Some(interpreter.clone())
        );
        let conflict = serde_json::json!({"version":1,"environment":{"CROW_DESKTOP_PYTHON_PATH":interpreter,"FAPAI_DESKTOP_PYTHON_PATH":root.join("different")}});
        std::fs::write(&config, conflict.to_string()).unwrap();
        assert_eq!(
            super::python_for_bundle(&root),
            Err(crate::environment_aliases::PYTHON_CONFLICT)
        );
        assert_eq!(
            std::fs::read(&interpreter).unwrap(),
            b"fixture only, never execute"
        );
        std::fs::remove_dir_all(&root).unwrap();
    }

    #[test]
    fn rejects_credential_bearing_and_non_api_urls() {
        for api in [
            "-ExecutionPolicy",
            "https://example.invalid\n",
            "file:///secret",
            "https://user:secret@example.invalid",
            "https://example.invalid?key=secret",
            "https://example.invalid/not-api",
        ] {
            let raw =
                serde_json::json!({"version":1,"environment":{"FAPAI_COLLECTOR_API_BASE":api}});
            assert_eq!(parse_api_base(raw.to_string().as_bytes()), Ok(None));
        }
    }
}
