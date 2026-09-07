//! System tray: four-colour status icon, context menu and the `tray-command` event.
//!
//! The UI derives the colour from the sidecar state (spec section 3) and calls
//! the `set_tray_state` command; menu clicks that need the sidecar are sent to
//! the UI as the `tray-command` event with payload `"connect"`, `"disconnect"`
//! or `"toggle_listen"`.

use log::warn;
use tauri::{
    image::Image,
    menu::{Menu, MenuItem, PredefinedMenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    AppHandle, Emitter, EventTarget, Manager, Runtime,
};

pub const TRAY_ID: &str = "main";
pub const TRAY_COMMAND_EVENT: &str = "tray-command";
const MAIN_WINDOW: &str = "main";

/// The four tray icons, decoded once at startup and kept in managed state.
pub struct TrayIcons {
    gray: Image<'static>,
    green: Image<'static>,
    blue: Image<'static>,
    yellow: Image<'static>,
}

impl TrayIcons {
    fn load() -> tauri::Result<Self> {
        Ok(Self {
            gray: Image::from_bytes(include_bytes!("../icons/tray-gray.png"))?,
            green: Image::from_bytes(include_bytes!("../icons/tray-green.png"))?,
            blue: Image::from_bytes(include_bytes!("../icons/tray-blue.png"))?,
            yellow: Image::from_bytes(include_bytes!("../icons/tray-yellow.png"))?,
        })
    }

    fn get(&self, state: TrayState) -> &Image<'static> {
        match state {
            TrayState::Gray => &self.gray,
            TrayState::Green => &self.green,
            TrayState::Blue => &self.blue,
            TrayState::Yellow => &self.yellow,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TrayState {
    /// glasses not connected
    Gray,
    /// connected, idle
    Green,
    /// listening
    Blue,
    /// Claude is waiting for input
    Yellow,
}

impl TrayState {
    pub fn parse(s: &str) -> Option<Self> {
        match s.trim().to_ascii_lowercase().as_str() {
            "gray" | "grey" => Some(Self::Gray),
            "green" => Some(Self::Green),
            "blue" => Some(Self::Blue),
            "yellow" => Some(Self::Yellow),
            _ => None,
        }
    }

    pub fn tooltip(self) -> &'static str {
        match self {
            Self::Gray => "Sidekick – getrennt",
            Self::Green => "Sidekick – verbunden",
            Self::Blue => "Sidekick – hört zu",
            Self::Yellow => "Sidekick – wartet auf Eingabe",
        }
    }
}

// ----------------------------------------------------------------------------- commands

/// Swap the tray icon and tooltip. Accepts `gray | green | blue | yellow`.
#[tauri::command]
pub fn set_tray_state(app: AppHandle, state: String) -> Result<(), String> {
    let parsed = TrayState::parse(&state)
        .ok_or_else(|| format!("unknown tray state '{state}' (expected gray|green|blue|yellow)"))?;
    apply_state(&app, parsed)
}

/// Show and focus the main window (used by the tray, single-instance and the UI).
#[tauri::command]
pub fn show_window(app: AppHandle) -> Result<(), String> {
    show_main_window(&app);
    Ok(())
}

// ----------------------------------------------------------------------------- setup

/// Build the tray icon with its menu and register the icon set in managed state.
pub fn build<R: Runtime>(app: &AppHandle<R>) -> tauri::Result<()> {
    let icons = TrayIcons::load()?;

    let open = MenuItem::with_id(app, "open", "Öffnen", true, None::<&str>)?;
    let connect = MenuItem::with_id(app, "connect", "Brille verbinden", true, None::<&str>)?;
    let disconnect = MenuItem::with_id(app, "disconnect", "Brille trennen", true, None::<&str>)?;
    let listen = MenuItem::with_id(app, "toggle_listen", "Zuhören an/aus", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "Beenden", true, None::<&str>)?;
    let menu = Menu::with_items(
        app,
        &[
            &open,
            &PredefinedMenuItem::separator(app)?,
            &connect,
            &disconnect,
            &listen,
            &PredefinedMenuItem::separator(app)?,
            &quit,
        ],
    )?;

    TrayIconBuilder::with_id(TRAY_ID)
        .icon(icons.get(TrayState::Gray).clone())
        .tooltip("Sidekick")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id().0.as_str() {
            "open" => show_main_window(app),
            "quit" => {
                crate::sidecar::shutdown(app);
                app.exit(0);
            }
            id @ ("connect" | "disconnect" | "toggle_listen") => emit_tray_command(app, id),
            other => warn!("unhandled tray menu item '{other}'"),
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                show_main_window(tray.app_handle());
            }
        })
        .build(app)?;

    app.manage(icons);
    Ok(())
}

// ----------------------------------------------------------------------------- helpers

pub fn show_main_window<R: Runtime>(app: &AppHandle<R>) {
    match app.get_webview_window(MAIN_WINDOW) {
        Some(window) => {
            let _ = window.show();
            let _ = window.unminimize();
            let _ = window.set_focus();
        }
        None => warn!("main window not found"),
    }
}

pub fn apply_state<R: Runtime>(app: &AppHandle<R>, state: TrayState) -> Result<(), String> {
    let tray = app
        .tray_by_id(TRAY_ID)
        .ok_or_else(|| "tray icon not initialised".to_string())?;
    let icons = app.state::<TrayIcons>();
    tray.set_icon(Some(icons.get(state).clone()))
        .map_err(|e| e.to_string())?;
    tray.set_tooltip(Some(state.tooltip()))
        .map_err(|e| e.to_string())
}

fn emit_tray_command<R: Runtime>(app: &AppHandle<R>, command: &str) {
    if let Err(e) = app.emit_to(EventTarget::labeled(MAIN_WINDOW), TRAY_COMMAND_EVENT, command) {
        warn!("failed to emit {TRAY_COMMAND_EVENT}: {e}");
    }
}
