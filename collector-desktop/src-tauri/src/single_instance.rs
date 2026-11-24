#[cfg(windows)]
mod imp {
    use std::ptr::null;
    use std::thread;

    const WAIT_OBJECT_0: u32 = 0x0000_0000;
    const WAIT_ABANDONED: u32 = 0x0000_0080;
    const WAIT_TIMEOUT: u32 = 0x0000_0102;
    const INFINITE: u32 = 0xFFFF_FFFF;
    const ASFW_ANY: u32 = 0xFFFF_FFFF;
    const UOI_NAME: i32 = 2;

    #[link(name = "kernel32")]
    extern "system" {
        fn GetCurrentThreadId() -> u32;
        fn CreateMutexW(attrs: *const u8, initial_owner: i32, name: *const u16) -> isize;
        fn CreateEventW(
            attrs: *const u8,
            manual_reset: i32,
            initial_state: i32,
            name: *const u16,
        ) -> isize;
        fn SetEvent(handle: isize) -> i32;
        fn WaitForSingleObject(handle: isize, milliseconds: u32) -> u32;
        fn ReleaseMutex(handle: isize) -> i32;
        fn CloseHandle(handle: isize) -> i32;
    }

    #[link(name = "user32")]
    extern "system" {
        fn AllowSetForegroundWindow(process_id: u32) -> i32;
        fn GetThreadDesktop(thread_id: u32) -> isize;
        fn GetUserObjectInformationW(
            obj: isize,
            index: i32,
            info: *mut u16,
            len: u32,
            needed: *mut u32,
        ) -> i32;
    }

    fn wide_null(name: &str) -> Vec<u16> {
        name.encode_utf16().chain(std::iter::once(0)).collect()
    }

    pub fn current_desktop_name() -> Option<String> {
        unsafe {
            let desktop = GetThreadDesktop(GetCurrentThreadId());
            if desktop == 0 {
                return None;
            }
            let mut buf = [0_u16; 128];
            let mut needed = 0_u32;
            let ok = GetUserObjectInformationW(
                desktop,
                UOI_NAME,
                buf.as_mut_ptr(),
                (buf.len() * std::mem::size_of::<u16>()) as u32,
                &mut needed,
            );
            if ok == 0 {
                return None;
            }
            let end = buf.iter().position(|&c| c == 0).unwrap_or(buf.len());
            Some(String::from_utf16_lossy(&buf[..end]))
        }
    }

    pub fn allow_current_desktop(desktop: Option<&str>, allow_headless_override: bool) -> bool {
        if allow_headless_override {
            return true;
        }
        match desktop {
            Some(name) => name.eq_ignore_ascii_case("Default"),
            None => true,
        }
    }

    pub struct ActivationListener {
        activate_event: usize,
    }

    impl ActivationListener {
        pub fn spawn<F>(self, on_activate: F)
        where
            F: Fn() + Send + 'static,
        {
            if self.activate_event == 0 {
                return;
            }
            thread::spawn(move || loop {
                // SAFETY: `activate_event` is an open auto-reset Win32 event handle.
                let wait = unsafe { WaitForSingleObject(self.activate_event as isize, INFINITE) };
                if wait == WAIT_OBJECT_0 {
                    on_activate();
                } else {
                    break;
                }
            });
        }
    }

    pub struct InstanceGuard {
        mutex: isize,
        activate_event: isize,
    }

    impl InstanceGuard {
        pub fn listener(&self) -> ActivationListener {
            ActivationListener {
                activate_event: self.activate_event as usize,
            }
        }
    }

    impl Drop for InstanceGuard {
        fn drop(&mut self) {
            unsafe {
                if self.activate_event != 0 {
                    let _ = CloseHandle(self.activate_event);
                }
                if self.mutex != 0 {
                    let _ = ReleaseMutex(self.mutex);
                    let _ = CloseHandle(self.mutex);
                }
            }
        }
    }

    pub fn acquire_or_signal(mutex_name: &str, event_name: &str) -> Option<InstanceGuard> {
        let mutex_w = wide_null(mutex_name);
        let event_w = wide_null(event_name);
        unsafe {
            let mutex = CreateMutexW(null(), 0, mutex_w.as_ptr());
            if mutex == 0 {
                return Some(InstanceGuard {
                    mutex: 0,
                    activate_event: 0,
                });
            }
            let event = CreateEventW(null(), 0, 0, event_w.as_ptr());
            match WaitForSingleObject(mutex, 0) {
                WAIT_OBJECT_0 | WAIT_ABANDONED => Some(InstanceGuard {
                    mutex,
                    activate_event: event,
                }),
                WAIT_TIMEOUT => {
                    let _ = AllowSetForegroundWindow(ASFW_ANY);
                    if event != 0 {
                        let _ = SetEvent(event);
                        let _ = CloseHandle(event);
                    }
                    let _ = CloseHandle(mutex);
                    None
                }
                _ => Some(InstanceGuard {
                    mutex,
                    activate_event: event,
                }),
            }
        }
    }
}

#[cfg(not(windows))]
mod imp {
    pub struct ActivationListener;

    impl ActivationListener {
        pub fn spawn<F>(self, _on_activate: F)
        where
            F: Fn() + Send + 'static,
        {
        }
    }

    pub struct InstanceGuard;

    impl InstanceGuard {
        pub fn listener(&self) -> ActivationListener {
            ActivationListener
        }
    }

    pub fn acquire_or_signal(_mutex_name: &str, _event_name: &str) -> Option<InstanceGuard> {
        Some(InstanceGuard)
    }
}

pub use imp::InstanceGuard;

pub fn acquire_default() -> Option<InstanceGuard> {
    #[cfg(windows)]
    {
        let allow_override =
            std::env::var("CROW_ALLOW_HEADLESS_DESKTOP").ok().as_deref() == Some("1");
        let desktop = imp::current_desktop_name();
        if !imp::allow_current_desktop(desktop.as_deref(), allow_override) {
            eprintln!(
                "Refusing to start Crow GUI on non-interactive Win32 desktop {:?}; launch from the interactive Default desktop.",
                desktop
            );
            return None;
        }
    }
    imp::acquire_or_signal(
        "Local\\com.fapaifang.collector.instance.v1",
        "Local\\com.fapaifang.collector.activate.v1",
    )
}

#[cfg(all(test, windows))]
mod tests {
    use super::imp::{acquire_or_signal, allow_current_desktop};
    use std::sync::mpsc;
    use std::thread;
    use std::time::Duration;

    #[test]
    fn non_default_win32_desktop_is_rejected_unless_explicitly_overridden() {
        assert!(allow_current_desktop(Some("Default"), false));
        assert!(allow_current_desktop(Some("default"), false));
        assert!(!allow_current_desktop(
            Some("exebox-VZNSXNCLPAUHMVDVT7NPZGMSEW"),
            false
        ));
        assert!(allow_current_desktop(
            Some("exebox-VZNSXNCLPAUHMVDVT7NPZGMSEW"),
            true
        ));
    }

    #[test]
    fn second_instance_signals_primary_and_exits_early() {
        let suffix = std::process::id();
        let mutex_name = format!("Local\\com.fapaifang.collector.test.mutex.{suffix}");
        let event_name = format!("Local\\com.fapaifang.collector.test.event.{suffix}");

        let primary = acquire_or_signal(&mutex_name, &event_name).expect("primary must acquire");
        let (tx, rx) = mpsc::channel();
        primary.listener().spawn(move || {
            let _ = tx.send(true);
        });

        let m2 = mutex_name.clone();
        let e2 = event_name.clone();
        let secondary_acquired = thread::spawn(move || acquire_or_signal(&m2, &e2).is_some())
            .join()
            .unwrap();
        assert!(!secondary_acquired);
        assert_eq!(rx.recv_timeout(Duration::from_secs(2)).ok(), Some(true));
        drop(primary);
    }
}
