// Simko SI desktop shell: starts the bundled Python backend (sidecar), then shows its UI.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::Duration;
use tauri::menu::{Menu, MenuItem, Submenu};
use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};

struct Backend(Mutex<Option<Child>>);
struct BaseUrl(Mutex<Option<String>>);

fn go(app: &tauri::AppHandle, page: &str) {
    let base = app.state::<BaseUrl>().0.lock().unwrap().clone();
    if let (Some(base), Some(w)) = (base, app.get_webview_window("main")) {
        if let Ok(u) = format!("{base}{page}").parse() {
            let _ = w.navigate(u);
        }
    }
}

fn sidecar_path() -> PathBuf {
    let exe = std::env::current_exe().expect("current exe");
    let dir = exe.parent().expect("exe dir").to_path_buf();
    let name = if cfg!(windows) { "simko-backend.exe" } else { "simko-backend" };
    dir.join(name)
}

fn spawn_backend() -> std::io::Result<Child> {
    let mut cmd = Command::new(sidecar_path());
    cmd.stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    cmd.spawn()
}

fn show_error(app: &tauri::AppHandle, msg: &str) {
    if let Some(w) = app.get_webview_window("main") {
        let js = format!("document.getElementById('e').textContent = {};", serde_json::to_string(msg).unwrap());
        let _ = w.eval(&js);
    }
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.unminimize();
                let _ = w.set_focus();
            }
        }))
        .manage(Backend(Mutex::new(None)))
        .manage(BaseUrl(Mutex::new(None)))
        .on_menu_event(|app, ev| match ev.id().as_ref() {
            "chat" => go(app, ""),
            "setup" => go(app, "setup"),
            _ => {}
        })
        .setup(|app| {
            let chat = MenuItem::with_id(app, "chat", "Chat", true, None::<&str>)?;
            let setup = MenuItem::with_id(app, "setup", "Setup and downloads", true, None::<&str>)?;
            let sub = Submenu::with_items(app, "Simko SI", true, &[&chat, &setup])?;
            app.set_menu(Menu::with_items(app, &[&sub])?)?;
            WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                .title("Simko SI")
                .inner_size(1180.0, 820.0)
                .min_inner_size(380.0, 560.0)
                .build()?;
            let handle = app.handle().clone();
            match spawn_backend() {
                Ok(mut child) => {
                    let stdout = child.stdout.take();
                    *app.state::<Backend>().0.lock().unwrap() = Some(child);
                    std::thread::spawn(move || {
                        let (tx, rx) = std::sync::mpsc::channel::<String>();
                        if let Some(out) = stdout {
                            std::thread::spawn(move || {
                                for line in BufReader::new(out).lines().map_while(Result::ok) {
                                    if let Some(rest) = line.strip_prefix("SIMKOSI_READY ") {
                                        let _ = tx.send(rest.to_string());
                                    }
                                }
                            });
                        }
                        match rx.recv_timeout(Duration::from_secs(90)) {
                            Ok(json) => {
                                let url = serde_json::from_str::<serde_json::Value>(&json)
                                    .ok()
                                    .and_then(|v| v.get("url").and_then(|u| u.as_str()).map(String::from))
                                    .unwrap_or_else(|| "http://127.0.0.1:8788/".into());
                                if let Ok(parsed) = url.parse::<tauri::Url>() {
                                    let base = format!("http://127.0.0.1:{}/", parsed.port().unwrap_or(8788));
                                    *handle.state::<BaseUrl>().0.lock().unwrap() = Some(base);
                                }
                                if let (Some(w), Ok(u)) = (handle.get_webview_window("main"), url.parse()) {
                                    let _ = w.navigate(u);
                                }
                            }
                            Err(_) => show_error(&handle, "Simko SI's engine did not start. Open the logs folder in your user AppData\\Local\\SimkoSI\\logs (Mac: ~/Library/Application Support/SimkoSI/logs) and send simko.log."),
                        }
                    });
                }
                Err(e) => show_error(&handle, &format!("Could not start Simko SI's engine: {e}")),
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building Simko SI")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                if let Some(mut child) = app.state::<Backend>().0.lock().unwrap().take() {
                    drop(child.stdin.take()); // backend exits when stdin closes
                    std::thread::sleep(Duration::from_millis(300));
                    let _ = child.kill();
                }
            }
        });
}
