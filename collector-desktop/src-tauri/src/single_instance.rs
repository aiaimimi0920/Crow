#[cfg(windows)]
mod imp {
    use std::ptr::null;
    use std::thread;

    const WAIT_OBJECT_0: u32 = 0x0000_0000;
    const WAIT_ABANDONED: u32 = 0x0000_0080;
    const WAIT_TIMEOUT: u32 = 0x0000_0102;
    const INFINITE: u32 = 0xFFFF_FFFF;
    const ASFW_ANY: u32 = 0xFFFF_FFFF;

    #[link(name = "kernel32")]
    extern "system" {
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
    }

    fn wide_null(name: &str) -> Vec<u16> {
        name.encode_utf16().chain(std::iter::once(0)).collect()
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
                // SAFETY: `activate_event` is a valid auto-reset Win32 event handle kept open
                // until process exit (or returns WAIT_FAILED if closed during shutdown).
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
    imp::acquire_or_signal(
        "Local\\com.fapaifang.collector.instance.v1",
        "Local\\com.fapaifang.collector.activate.v1",
    )
}

#[cfg(all(test, windows))]
mod tests {
    use super::imp::acquire_or_signal;
    use std::sync::mpsc;
    use std::thread;
    use std::time::Duration;

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
