//! Lifecycle of the Python sidecar (`python -m sidekick`).
//!
//! Debug builds run the sidecar from the checkout via `uv run`; release builds
//! run the PyInstaller binary bundled as a Tauri external binary. Either way the
//! child is supervised: if it exits it is restarted after [`RESTART_DELAY`], at
//! most [`MAX_RESTARTS`] times per [`RESTART_WINDOW`]. Every state change is
//! broadcast to the main window as the `sidecar-status` event with payload
//! `{ running: bool, message?: string }`.

use std::{
    sync::Mutex,
    thread,
    time::{Duration, Instant},
};

use log::{debug, error, info, warn};
use serde::Serialize;
use tauri::{async_runtime::Receiver, AppHandle, Emitter, EventTarget, Manager, Runtime, State};
use tauri_plugin_shell::{
    process::{Command, CommandChild, CommandEvent},
    ShellExt,
};

/// Fixed sidecar port (see design spec section 2; hook URLs depend on it).
pub const SIDECAR_PORT: u16 = 47821;
/// Tauri event carrying a [`SidecarStatus`] payload.
pub const STATUS_EVENT: &str = "sidecar-status";
/// Label of the window that receives status events.
const MAIN_WINDOW: &str = "main";

const RESTART_DELAY: Duration = Duration::from_secs(2);
const MAX_RESTARTS: usize = 3;
const RESTART_WINDOW: Duration = Duration::from_secs(5 * 60);

/// Payload of the `sidecar-status` event and result of the `sidecar_status` command.
#[derive(Debug, Clone, Serialize)]
pub struct SidecarStatus {
    pub running: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub message: Option<String>,
}

/// Supervisor state, stored in Tauri managed state as [`SidecarState`].
#[derive(Default)]
pub struct SidecarManager {
    child: Option<CommandChild>,
    /// Incremented on every spawn and every deliberate kill. A pump task whose
    /// generation no longer matches knows its child was replaced on purpose and
    /// must not trigger a restart.
    generation: u64,
    /// Timestamps of automatic restarts inside the current window.
    restarts: Vec<Instant>,
    shutting_down: bool,
    running: bool,
    last_message: Option<String>,
}

pub type SidecarState = Mutex<SidecarManager>;

// ----------------------------------------------------------------------------- commands

/// Kill the running sidecar (if any) and start a fresh one. Resets the restart budget.
#[tauri::command]
pub fn restart_sidecar(app: AppHandle) -> Result<(), String> {
    info!("manual sidecar restart requested");
    {
        let state = app.state::<SidecarState>();
        let mut mgr = state.lock().map_err(|e| e.to_string())?;
        mgr.generation += 1;
        if let Some(child) = mgr.child.take() {
            kill_child(child);
        }
        mgr.restarts.clear();
        mgr.running = false;
    }
    spawn(&app)
}

/// Current supervisor status (`running` plus the last human-readable message).
#[tauri::command]
pub fn sidecar_status(state: State<'_, SidecarState>) -> Result<SidecarStatus, String> {
    let mgr = state.lock().map_err(|e| e.to_string())?;
    Ok(SidecarStatus {
        running: mgr.running,
        message: mgr.last_message.clone(),
    })
}

// ----------------------------------------------------------------------------- lifecycle

/// Start the sidecar; on failure fall into the same restart budget as a crash.
pub fn start<R: Runtime>(app: &AppHandle<R>) {
    if let Err(e) = spawn(app) {
        error!("sidecar failed to start: {e}");
        schedule_restart(app, format!("Sidecar konnte nicht gestartet werden: {e}"));
    }
}

/// Stop supervising and kill the child. Called on app exit and from "Beenden".
pub fn shutdown<R: Runtime>(app: &AppHandle<R>) {
    let state = app.state::<SidecarState>();
    let Ok(mut mgr) = state.lock() else {
        return;
    };
    mgr.shutting_down = true;
    mgr.generation += 1;
    mgr.running = false;
    if let Some(child) = mgr.child.take() {
        info!("shutting down sidecar");
        kill_child(child);
    }
}

fn spawn<R: Runtime>(app: &AppHandle<R>) -> Result<(), String> {
    let state = app.state::<SidecarState>();
    let mut mgr = state.lock().map_err(|e| e.to_string())?;
    if mgr.shutting_down {
        return Ok(());
    }
    if let Some(child) = mgr.child.take() {
        // defensive: never run two sidecars at once
        mgr.generation += 1;
        kill_child(child);
    }

    let command = build_command(app).map_err(|e| e.to_string())?;
    let (rx, child) = command.spawn().map_err(|e| e.to_string())?;

    mgr.generation += 1;
    let generation = mgr.generation;
    let pid = child.pid();
    mgr.child = Some(child);
    mgr.running = true;
    mgr.last_message = None;
    drop(mgr);

    info!("sidecar started (pid {pid}, generation {generation}, port {SIDECAR_PORT})");
    emit_status(
        app,
        SidecarStatus {
            running: true,
            message: None,
        },
    );

    let app = app.clone();
    tauri::async_runtime::spawn(async move { pump_events(app, rx, generation).await });
    Ok(())
}

/// Forward the child's output to the log and react to its termination.
async fn pump_events<R: Runtime>(app: AppHandle<R>, mut rx: Receiver<CommandEvent>, generation: u64) {
    let mut exit_message: Option<String> = None;
    while let Some(event) = rx.recv().await {
        match event {
            CommandEvent::Stdout(line) => {
                info!(target: "sidecar", "{}", String::from_utf8_lossy(&line).trim_end());
            }
            CommandEvent::Stderr(line) => {
                // Python logging writes to stderr, so this is normal output, not an error.
                info!(target: "sidecar", "{}", String::from_utf8_lossy(&line).trim_end());
            }
            CommandEvent::Error(e) => warn!(target: "sidecar", "io error: {e}"),
            CommandEvent::Terminated(payload) => {
                exit_message = Some(match payload.code {
                    Some(code) => format!("Sidecar beendet (Exit-Code {code})"),
                    None => "Sidecar beendet (kein Exit-Code)".to_string(),
                });
                break;
            }
            _ => {}
        }
    }

    {
        let state = app.state::<SidecarState>();
        let Ok(mut mgr) = state.lock() else {
            return;
        };
        if mgr.generation != generation || mgr.shutting_down {
            debug!("sidecar generation {generation} ended deliberately; no restart");
            return;
        }
        mgr.child = None;
        mgr.running = false;
    }

    let reason = exit_message.unwrap_or_else(|| "Sidecar-Verbindung abgerissen".to_string());
    warn!("{reason}");
    schedule_restart(&app, reason);
}

/// Apply the restart budget: restart after a delay or give up and report.
fn schedule_restart<R: Runtime>(app: &AppHandle<R>, reason: String) {
    let state = app.state::<SidecarState>();
    let Ok(mut mgr) = state.lock() else {
        return;
    };
    mgr.running = false;
    if mgr.shutting_down {
        return;
    }

    let now = Instant::now();
    mgr.restarts.retain(|t| now.duration_since(*t) < RESTART_WINDOW);

    if mgr.restarts.len() >= MAX_RESTARTS {
        let message = format!(
            "{reason} – nach {MAX_RESTARTS} Neustarts in 5 Minuten aufgegeben. \
             Manuell über „Sidecar neu starten“ versuchen."
        );
        error!("{message}");
        mgr.last_message = Some(message.clone());
        drop(mgr);
        emit_status(
            app,
            SidecarStatus {
                running: false,
                message: Some(message),
            },
        );
        return;
    }

    mgr.restarts.push(now);
    let attempt = mgr.restarts.len();
    let message = format!(
        "{reason} – Neustart {attempt}/{MAX_RESTARTS} in {} s",
        RESTART_DELAY.as_secs()
    );
    warn!("{message}");
    mgr.last_message = Some(message.clone());
    drop(mgr);
    emit_status(
        app,
        SidecarStatus {
            running: false,
            message: Some(message),
        },
    );

    let app = app.clone();
    thread::Builder::new()
        .name("sidecar-restart".into())
        .spawn(move || {
            thread::sleep(RESTART_DELAY);
            start(&app);
        })
        .ok();
}

// ----------------------------------------------------------------------------- helpers

/// Debug: `uv run --project <repo>/sidecar python -m sidekick --port … --parent-pid …`.
#[cfg(debug_assertions)]
fn build_command<R: Runtime>(app: &AppHandle<R>) -> Result<Command, tauri_plugin_shell::Error> {
    use std::path::Path;

    let repo = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("src-tauri has a parent directory");
    let project = repo.join("sidecar");
    Ok(app
        .shell()
        .command("uv")
        .args(["run", "--project"])
        .arg(&project)
        .args(["python", "-m", "sidekick", "--port"])
        .arg(SIDECAR_PORT.to_string())
        .arg("--parent-pid")
        .arg(std::process::id().to_string())
        .current_dir(&project)
        .env("PYTHONUTF8", "1")
        .env("PYTHONUNBUFFERED", "1"))
}

/// Release: the PyInstaller binary bundled as `binaries/sidekick-sidecar`.
#[cfg(not(debug_assertions))]
fn build_command<R: Runtime>(app: &AppHandle<R>) -> Result<Command, tauri_plugin_shell::Error> {
    Ok(app
        .shell()
        // Rust API takes the bare sidecar name; the bundler places it as <exe dir>\sidekick-sidecar.exe
        .sidecar("sidekick-sidecar")?
        .args(["--port"])
        .arg(SIDECAR_PORT.to_string())
        .arg("--parent-pid")
        .arg(std::process::id().to_string())
        .env("PYTHONUTF8", "1")
        .env("PYTHONUNBUFFERED", "1"))
}

/// Kill the child and, on Windows, its whole process tree (in debug builds `uv`
/// wraps `python`, which would otherwise survive as an orphan).
fn kill_child(child: CommandChild) {
    let pid = child.pid();
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        match std::process::Command::new("taskkill")
            .args(["/PID", &pid.to_string(), "/T", "/F"])
            .creation_flags(CREATE_NO_WINDOW)
            .output()
        {
            Ok(out) if out.status.success() => debug!("taskkill /T {pid} ok"),
            Ok(out) => debug!(
                "taskkill /T {pid}: {}",
                String::from_utf8_lossy(&out.stderr).trim_end()
            ),
            Err(e) => warn!("taskkill unavailable: {e}"),
        }
    }
    if let Err(e) = child.kill() {
        debug!("child.kill({pid}) after tree kill: {e}");
    }
}

fn emit_status<R: Runtime>(app: &AppHandle<R>, status: SidecarStatus) {
    if let Err(e) = app.emit_to(EventTarget::labeled(MAIN_WINDOW), STATUS_EVENT, status) {
        warn!("failed to emit {STATUS_EVENT}: {e}");
    }
}
