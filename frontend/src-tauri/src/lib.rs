/// Tauri shell entry point (TS-1).
///
/// The desktop shell only opens the bundled web frontend (built to `../dist`).
/// All AImation Flow logic lives in the Vite/React bundle; there are no Rust
/// commands in v0.1. The extension points (menu, commands, tray) land in later
/// phases.
#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("error while running AImation Flow");
}
