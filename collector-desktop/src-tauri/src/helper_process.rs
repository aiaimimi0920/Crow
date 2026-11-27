use std::io::{Read, Write};
use std::process::{Command, Output, Stdio};
use std::sync::mpsc;
use std::thread;
use std::time::{Duration, Instant};

pub fn run(
    command: &mut Command,
    input: Vec<u8>,
    timeout: Duration,
) -> Result<Output, &'static str> {
    command
        .stdin(if input.is_empty() {
            Stdio::null()
        } else {
            Stdio::piped()
        })
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    let mut child = command.spawn().map_err(|_| "helper_start_failed")?;
    let stdout = child.stdout.take().ok_or("helper_output_unavailable")?;
    let mut stderr = child.stderr.take().ok_or("helper_output_unavailable")?;
    let (sender, receiver) = mpsc::channel();
    let (error_sender, error_receiver) = mpsc::channel();
    // Neither a full input/output pipe nor a silent child may hold the UI gate.
    if let Some(mut stdin) = child.stdin.take() {
        thread::spawn(move || {
            let _ = stdin.write_all(&input);
        });
    }
    thread::spawn(move || {
        let mut bytes = Vec::new();
        let mut buffer = [0_u8; 4096];
        while let Ok(count) = stderr.read(&mut buffer) {
            if count == 0 {
                break;
            }
            let kept = count.min(8192 - bytes.len());
            bytes.extend_from_slice(&buffer[..kept]);
        }
        let _ = error_sender.send(bytes);
    });
    thread::spawn(move || {
        let mut bytes = Vec::new();
        let result = stdout.take(65537).read_to_end(&mut bytes).map(|_| bytes);
        let _ = sender.send(result);
    });
    let deadline = Instant::now() + timeout;
    let result = match receiver.recv_timeout(deadline.saturating_duration_since(Instant::now())) {
        Ok(Ok(stdout)) if stdout.len() <= 65536 => {
            match error_receiver.recv_timeout(deadline.saturating_duration_since(Instant::now())) {
                Ok(stderr) => loop {
                    match child.try_wait() {
                        Ok(Some(status)) => {
                            break Ok(Output {
                                status,
                                stdout,
                                stderr,
                            });
                        }
                        Err(_) => break Err("helper_wait_failed"),
                        Ok(None) => {
                            if Instant::now() >= deadline {
                                break Err("helper_timeout");
                            }
                            thread::sleep(Duration::from_millis(2));
                        }
                    }
                },
                Err(_) => Err("helper_timeout"),
            }
        }
        Ok(_) => Err("helper_output_invalid"),
        Err(_) => Err("helper_timeout"),
    };
    if result.is_err() {
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            let _ = Command::new("taskkill.exe")
                .args(["/T", "/F", "/PID", &child.id().to_string()])
                .creation_flags(0x08000000)
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .status();
        }
        let _ = child.kill();
        let _ = child.wait();
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sleeper() -> Command {
        #[cfg(windows)]
        {
            let mut command = Command::new("powershell.exe");
            command.args(["-NoProfile", "-Command", "Start-Sleep -Seconds 10"]);
            command
        }
        #[cfg(not(windows))]
        {
            let mut command = Command::new("sleep");
            command.arg("10");
            command
        }
    }

    #[test]
    fn silent_helper_has_a_total_deadline() {
        let started = Instant::now();
        assert_eq!(
            run(&mut sleeper(), Vec::new(), Duration::from_millis(100)).unwrap_err(),
            "helper_timeout"
        );
        assert!(started.elapsed() < Duration::from_secs(5));
    }

    #[test]
    fn blocked_stdin_does_not_bypass_deadline() {
        assert_eq!(
            run(
                &mut sleeper(),
                vec![b'x'; 20000],
                Duration::from_millis(100)
            )
            .unwrap_err(),
            "helper_timeout"
        );
    }

    #[test]
    fn stderr_is_bounded_and_drained_without_blocking_the_helper() {
        #[cfg(windows)]
        let mut command = {
            let mut command = Command::new("powershell.exe");
            command.args([
                "-NoProfile",
                "-Command",
                "[Console]::Error.Write(('x' * 131072)); [Console]::Out.Write('ok')",
            ]);
            command
        };
        #[cfg(not(windows))]
        let mut command = {
            let mut command = Command::new("sh");
            command.args(["-c", "printf '%131072s' x >&2; printf ok"]);
            command
        };
        let output = run(&mut command, Vec::new(), Duration::from_secs(20)).unwrap();
        assert!(output.status.success());
        assert_eq!(output.stdout, b"ok");
        assert_eq!(output.stderr.len(), 8192);
    }
}
