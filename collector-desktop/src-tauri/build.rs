mod build_frontend;

fn main() {
    println!("cargo:rerun-if-changed=icons/icon.ico");
    println!("cargo:rerun-if-changed=build_frontend.rs");
    println!("cargo:rerun-if-env-changed=TAURI_CONFIG");
    let config = std::fs::read_to_string("tauri.conf.json").expect("read Tauri configuration");
    build_frontend::validate_config(&config).expect("invalid Crow frontend configuration");
    if let Ok(overrides) = std::env::var("TAURI_CONFIG") {
        build_frontend::validate_config(&overrides).expect("invalid Crow frontend override");
    }
    tauri_build::build()
}
