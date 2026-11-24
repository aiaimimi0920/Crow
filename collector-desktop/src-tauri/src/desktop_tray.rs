use std::sync::atomic::{AtomicBool, Ordering};
use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Manager, WebviewWindowBuilder, Window, WindowEvent,
};

static EXITING: AtomicBool = AtomicBool::new(false);

pub fn show_main(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
        return;
    }
    if let Some(config) = app.config().app.windows.first() {
        if let Ok(builder) = WebviewWindowBuilder::from_config(app, config) {
            if let Ok(window) = builder.build() {
                let _ = window.show();
                let _ = window.set_focus();
            }
        }
    }
}

pub fn handle_window_event(window: &Window, event: &WindowEvent) {
    if window.label() == "main" && !EXITING.load(Ordering::Acquire) {
        if let WindowEvent::CloseRequested { api, .. } = event {
            api.prevent_close();
            let _ = window.hide();
        }
    }
}

pub fn install(app: &tauri::App) -> Result<(), Box<dyn std::error::Error>> {
    EXITING.store(false, Ordering::Release);
    let show = MenuItem::with_id(app, "show", "打开 Crow", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "退出 Crow", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&show, &quit])?;
    let icon = app
        .default_window_icon()
        .ok_or("Crow application icon is missing")?
        .clone();
    TrayIconBuilder::with_id("crow")
        .icon(icon)
        .tooltip("Crow 运维观察台")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "show" => show_main(app),
            "quit" => {
                EXITING.store(true, Ordering::Release);
                app.exit(0);
            }
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if matches!(
                event,
                TrayIconEvent::Click {
                    button: MouseButton::Left,
                    button_state: MouseButtonState::Up,
                    ..
                }
            ) {
                show_main(tray.app_handle());
            }
        })
        .build(app)?;
    Ok(())
}
