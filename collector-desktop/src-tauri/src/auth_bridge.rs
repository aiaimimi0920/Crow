use serde::Deserialize;
use serde_json::Value;
use std::process::Command;
use std::sync::atomic::{AtomicBool, Ordering};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

static ACTIVE: AtomicBool = AtomicBool::new(false);

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AuthRequest {
    action: String,
    api_base: String,
    #[serde(default)]
    target_url: String,
    #[serde(default)]
    target_id: String,
    #[serde(default)]
    request_id: String,
    #[serde(default)]
    challenge_id: String,
    #[serde(default)]
    recovery_id: String,
    #[serde(default)]
    scope: String,
    #[serde(default)]
    peer_url: String,
    #[serde(default)]
    peer_challenge_id: String,
    #[serde(default)]
    browser: String,
}

struct ActionGuard;
impl Drop for ActionGuard {
    fn drop(&mut self) {
        ACTIVE.store(false, Ordering::Release);
    }
}

fn decode_result(raw: &[u8]) -> Result<Value, String> {
    let line = raw
        .split(|byte| *byte == b'\n')
        .rev()
        .find_map(|line| line.strip_prefix(b"CROW_AUTH_RESULT="))
        .ok_or("认证助手没有返回结果，请检查本机安装")?;
    let payload = std::str::from_utf8(line).map_err(|_| "认证助手返回格式无效")?;
    if payload.len() > 8192 {
        return Err("认证助手返回结果过大".into());
    }
    let result: Value = serde_json::from_str(payload).map_err(|_| "认证助手返回格式无效")?;
    if !matches!(
        result.get("phase").and_then(Value::as_str),
        Some(
            "ready_for_human"
                | "pending_human"
                | "pending_pc2"
                | "succeeded"
                | "failed"
                | "unavailable"
        )
    ) {
        return Err("认证助手返回状态无效".into());
    }
    Ok(result)
}

fn execute(request: AuthRequest) -> Result<Value, String> {
    let api_base = super::runtime_config::validate_api_base(&request.api_base)
        .ok_or("Invalid authentication API URL")?;
    if !matches!(request.action.as_str(), "open" | "complete" | "status") {
        return Err("不支持的认证操作".into());
    }
    if !matches!(request.scope.as_str(), "" | "seed" | "detail") {
        return Err("认证阶段无效".into());
    }
    if !matches!(request.browser.as_str(), "" | "dedicated" | "edge") {
        return Err("认证浏览器无效".into());
    }
    if ACTIVE
        .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
        .is_err()
    {
        return Err("认证操作正在进行，请稍候".into());
    }
    let _guard = ActionGuard;
    let script = super::bundled_script_path("desktop-auth-challenge.ps1")
        .ok_or("本机认证助手未安装，请更新完整认证组件")?;
    let mut command = Command::new("powershell.exe");
    command.args(["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", &script]);
    for (name, value) in [
        ("-Action", request.action),
        ("-ApiBase", api_base),
        ("-TargetUrl", request.target_url),
        ("-TargetId", request.target_id),
        ("-RequestId", request.request_id),
        ("-ChallengeId", request.challenge_id),
        ("-RecoveryId", request.recovery_id),
        ("-Scope", request.scope),
        ("-PeerUrl", request.peer_url),
        ("-PeerChallengeId", request.peer_challenge_id),
        ("-Browser", request.browser),
    ] {
        if value.len() > 8192 || value.chars().any(char::is_control) || value.starts_with('-') {
            return Err("认证参数无效".into());
        }
        if !value.is_empty() {
            command.args([name, &value]);
        }
    }
    #[cfg(windows)]
    command.creation_flags(0x08000000);
    let output = super::helper_process::run(
        &mut command,
        Vec::new(),
        std::time::Duration::from_secs(180),
    )
    .map_err(|code| {
        eprintln!("Authentication helper failed: {code}");
        format!("认证助手未完成请求（{code}）；请查询同步状态，不要重复提交认证任务")
    })?;
    if !output.status.success() {
        eprintln!(
            "Authentication helper exit={:?}, stderr_bytes={}",
            output.status.code(),
            output.stderr.len()
        );
        return Err("本机认证助手执行失败（helper_exit_failed），请检查 Python 和运行文件".into());
    }
    decode_result(&output.stdout)
}

#[tauri::command]
pub async fn desktop_auth_action(request: AuthRequest) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || execute(request))
        .await
        .map_err(|_| "认证后台任务异常")?
}

#[cfg(test)]
mod tests {
    use super::{decode_result, AuthRequest};

    #[test]
    fn stage_identity_is_accepted_without_dropping_request_fields() {
        for scope in ["seed", "detail"] {
            let request: AuthRequest = serde_json::from_value(serde_json::json!({
                "action": "complete", "api_base": "http://fixture.invalid", "scope": scope,
                "request_id": "fixture", "challenge_id": "challenge", "target_id": "selected",
                "peer_url": "https://sf.taobao.com/list/50025969.htm", "peer_challenge_id": "peer"
            }))
            .unwrap();
            assert_eq!(request.scope, scope);
            assert_eq!(request.target_id, "selected");
            assert_eq!(request.challenge_id, "challenge");
            assert_eq!(request.peer_challenge_id, "peer");
            assert_eq!(request.peer_url, "https://sf.taobao.com/list/50025969.htm");
        }
    }

    #[test]
    fn pending_is_structured_and_raw_script_output_is_not_an_error_message() {
        let value =
            decode_result(b"helper log\xff\nCROW_AUTH_RESULT={\"phase\":\"pending_human\"}\r\n")
                .unwrap();
        assert_eq!(value["phase"], "pending_human");
        assert!(!decode_result(b"sensitive helper failure")
            .unwrap_err()
            .contains("sensitive"));
        assert!(decode_result(b"CROW_AUTH_RESULT={\"phase\":\"invented\"}").is_err());
    }
}
