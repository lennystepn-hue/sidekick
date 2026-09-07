fn main() {
    ensure_windres_on_path();
    tauri_build::build()
}

/// On `*-pc-windows-gnu`, `tauri_build` embeds the icon and application manifest with
/// GNU `windres` (via `embed-resource`), which it only looks up on `PATH`, and windres in
/// turn preprocesses the `.rc` file with a driver hard-wired as `gcc`.
///
/// This machine builds with the windows-gnu toolchain because it has no MSVC Build Tools
/// (see `rust-toolchain.toml` and `.cargo/config.toml`); its MinGW binutils live in the
/// MSYS2 install, are not on `PATH`, and that install ships the gcc driver only as
/// `cc.exe`. So, for this build-script process only:
///   1. prepend the MinGW `bin` directory (windres, and the DLLs `cc1.exe` needs), and
///   2. if no `gcc.exe` is reachable but `cc.exe` is, prepend a generated `gcc.bat`
///      shim (in `OUT_DIR`) that forwards to `cc.exe`.
/// Nothing outside the build (the app itself, `cargo run`, the sidecar) sees this.
///
/// Override the location with `SIDEKICK_MINGW_BIN=<dir containing windres.exe>`.
/// No-op on msvc targets and whenever `windres` is already reachable.
fn ensure_windres_on_path() {
    use std::path::{Path, PathBuf};

    println!("cargo:rerun-if-env-changed=SIDEKICK_MINGW_BIN");
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() != Ok("windows")
        || std::env::var("CARGO_CFG_TARGET_ENV").as_deref() != Ok("gnu")
    {
        return;
    }

    let path = std::env::var_os("PATH").unwrap_or_default();
    let path_dirs: Vec<PathBuf> = std::env::split_paths(&path).collect();
    let reachable = |exe: &str| path_dirs.iter().any(|dir| dir.join(exe).is_file());
    if reachable("windres.exe") {
        return;
    }

    let mut candidates: Vec<PathBuf> = Vec::new();
    if let Some(dir) = std::env::var_os("SIDEKICK_MINGW_BIN") {
        candidates.push(dir.into());
    }
    candidates.extend(
        [
            r"C:\msys64\mingw64\bin",
            r"C:\msys64\ucrt64\bin",
            r"C:\mingw64\bin",
            r"C:\TDM-GCC-64\bin",
        ]
        .iter()
        .map(PathBuf::from),
    );

    let Some(mingw_bin) = candidates.into_iter().find(|dir| dir.join("windres.exe").is_file()) else {
        println!(
            "cargo:warning=windres.exe not found; install MSYS2 mingw-w64 binutils or set \
             SIDEKICK_MINGW_BIN (resource embedding will fail on windows-gnu)"
        );
        return;
    };

    let mut prepend: Vec<PathBuf> = vec![mingw_bin.clone()];

    // windres shells out to `gcc -E`; provide the name if only `cc.exe` exists.
    let gcc_reachable = reachable("gcc.exe") || mingw_bin.join("gcc.exe").is_file();
    if !gcc_reachable {
        let driver = ["cc.exe", "cpp.exe"]
            .iter()
            .map(|d| mingw_bin.join(d))
            .find(|p| p.is_file());
        match (driver, std::env::var_os("OUT_DIR")) {
            (Some(driver), Some(out_dir)) => {
                let shim_dir = Path::new(&out_dir).join("mingw-shim");
                let shim = shim_dir.join("gcc.bat");
                let body = format!("@\"{}\" %*\r\n", driver.display());
                if std::fs::create_dir_all(&shim_dir)
                    .and_then(|_| std::fs::write(&shim, body))
                    .is_ok()
                {
                    prepend.insert(0, shim_dir);
                } else {
                    println!("cargo:warning=could not write {}", shim.display());
                }
            }
            _ => println!(
                "cargo:warning=no gcc/cc driver next to windres in {}; windres preprocessing will fail",
                mingw_bin.display()
            ),
        }
    }

    prepend.extend(path_dirs);
    if let Ok(new_path) = std::env::join_paths(prepend) {
        // Only this build-script process is affected; `embed-resource` spawns `windres`
        // (and windres spawns gcc) with the process environment.
        std::env::set_var("PATH", new_path);
        println!("cargo:warning=windows-gnu: using windres from {}", mingw_bin.display());
    }
}
