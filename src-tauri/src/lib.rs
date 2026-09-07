//! Sidekick desktop shell: window, tray, autostart and the Python sidecar's lifecycle.
//!
//! The UI (Vue, `../src`) talks to the sidecar directly over HTTP/WebSocket on
//! port 47821; this crate only hosts the webview, paints the tray and keeps the
//! sidecar alive. See `docs/superpowers/specs/2026-09-07-sidekick-design.md`.

mod sidecar;
mod tray;

use log::{info, warn};
use tauri::{Manager, RunEvent, WindowEvent};
use tauri_plugin_autostart::MacosLauncher;
use tauri_plugin_log::{Target, TargetKind};

/// Argument the autostart entry launches us with; the window then starts hidden in the tray.
const AUTOSTART_FLAG: &str = "--autostart";

pub fn run() {
    let app = tauri::Builder::default()
        // must be the first plugin so a second launch is intercepted before anything else runs
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            info!("second instance launched; focusing existing window");
            tray::show_main_window(app);
        }))
        .plugin(
            tauri_plugin_log::Builder::new()
                .level(log::LevelFilter::Info)
                .level_for("sidecar", log::LevelFilter::Info)
                .targets([
                    Target::new(TargetKind::Stdout),
                    Target::new(TargetKind::LogDir {
                        file_name: Some("sidekick".into()),
                    }),
                ])
                .build(),
        )
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_autostart::init(
            MacosLauncher::LaunchAgent,
            Some(vec![AUTOSTART_FLAG]),
        ))
        .manage(sidecar::SidecarState::default())
        .invoke_handler(tauri::generate_handler![
            tray::set_tray_state,
            tray::show_window,
            sidecar::restart_sidecar,
            sidecar::sidecar_status,
        ])
        .setup(|app| {
            let handle = app.handle();
            tray::build(handle)?;

            if std::env::args().any(|a| a == AUTOSTART_FLAG) {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.hide();
                }
            }

            sidecar::start(handle);
            Ok(())
        })
        .on_window_event(|window, event| {
            // closing the main window only hides it; "Beenden" in the tray quits
            if let WindowEvent::CloseRequested { api, .. } = event {
                if window.label() == "main" {
                    api.prevent_close();
                    if let Err(e) = window.hide() {
                        warn!("failed to hide main window: {e}");
                    }
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building Sidekick");

    app.run(|app, event| match event {
        RunEvent::ExitRequested { .. } | RunEvent::Exit => sidecar::shutdown(app),
        _ => {}
    });
}
