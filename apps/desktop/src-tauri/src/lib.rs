use std::{
    fs,
    net::{Ipv4Addr, SocketAddrV4, TcpListener, TcpStream},
    path::PathBuf,
    sync::Mutex,
    thread,
    time::{Duration, Instant},
};

use tauri::{Manager, RunEvent, State, WindowEvent};
use tauri_plugin_shell::{process::CommandChild, ShellExt};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

struct BackendState {
    url: String,
    token: String,
    child: Mutex<Option<CommandChild>>,
}

#[tauri::command]
fn backend_url(state: State<'_, BackendState>) -> String {
    state.url.clone()
}

#[tauri::command]
fn backend_token(state: State<'_, BackendState>) -> String {
    state.token.clone()
}

fn reserve_local_port() -> Result<u16, Box<dyn std::error::Error>> {
    let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0))?;
    Ok(listener.local_addr()?.port())
}

fn wait_for_backend(port: u16, timeout: Duration) -> Result<(), Box<dyn std::error::Error>> {
    let address = SocketAddrV4::new(Ipv4Addr::LOCALHOST, port);
    let deadline = Instant::now() + timeout;

    while Instant::now() < deadline {
        if TcpStream::connect_timeout(&address.into(), Duration::from_millis(100)).is_ok() {
            return Ok(());
        }
        thread::sleep(Duration::from_millis(100));
    }

    Err(format!("desktop API did not start on port {port}").into())
}

fn find_legacy_data_dir() -> Option<PathBuf> {
    let mut candidates = Vec::new();

    if let Ok(current_dir) = std::env::current_dir() {
        candidates.push(current_dir.join("services/data"));
        candidates.push(current_dir.join("../../services/data"));
    }
    if let Ok(executable) = std::env::current_exe() {
        if let Some(executable_dir) = executable.parent() {
            candidates.push(executable_dir.join("services/data"));
            candidates.push(executable_dir.join("data"));
        }
    }
    if cfg!(debug_assertions) {
        candidates
            .push(std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../services/data"));
    }

    candidates.into_iter().find(|path| path.is_dir())
}

fn terminate_backend(child: CommandChild) {
    #[cfg(windows)]
    {
        const CREATE_NO_WINDOW: u32 = 0x08000000;
        let _ = std::process::Command::new("taskkill")
            .args(["/PID", &child.pid().to_string(), "/T", "/F"])
            .creation_flags(CREATE_NO_WINDOW)
            .status();
    }

    let _ = child.kill();
}

fn stop_backend(app_handle: &tauri::AppHandle) {
    if let Some(state) = app_handle.try_state::<BackendState>() {
        if let Ok(mut child) = state.child.lock() {
            if let Some(child) = child.take() {
                terminate_backend(child);
            }
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![backend_url, backend_token])
        .on_window_event(|window, event| {
            if matches!(event, WindowEvent::CloseRequested { .. }) {
                stop_backend(window.app_handle());
            }
        })
        .setup(|app| {
            let port = reserve_local_port()?;
            let token = uuid::Uuid::new_v4().simple().to_string();
            let data_dir = app.path().app_data_dir()?.join("data");
            fs::create_dir_all(&data_dir)?;

            let mut args = vec![
                "--port".to_string(),
                port.to_string(),
                "--data-dir".to_string(),
                data_dir.to_string_lossy().into_owned(),
                "--parent-pid".to_string(),
                std::process::id().to_string(),
                "--api-token".to_string(),
                token.clone(),
            ];

            if let Some(legacy_data_dir) = find_legacy_data_dir() {
                args.push("--legacy-data-dir".to_string());
                args.push(legacy_data_dir.to_string_lossy().into_owned());
            }

            let (mut events, child) = app
                .shell()
                .sidecar("ai-paper-coach-api")?
                .args(args)
                .spawn()?;

            tauri::async_runtime::spawn(async move { while events.recv().await.is_some() {} });

            wait_for_backend(port, Duration::from_secs(20))?;
            app.manage(BackendState {
                url: format!("http://127.0.0.1:{port}"),
                token,
                child: Mutex::new(Some(child)),
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building AI Paper Coach");

    app.run(|app_handle, event| {
        if let RunEvent::Exit = event {
            stop_backend(app_handle);
        }
    });
}
