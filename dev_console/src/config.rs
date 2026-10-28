// ==== Generic Company Inc. portfolio ====================================
// Project: portfolio | File: dev_console/src/config.rs
// About: The config fileset: config/settings.ini and config/controls.ini, layered as built-in...
// Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
// You may change this file under the AGPL-3.0. The stamp at the end marks
// the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
// ========================================================================

//! The config fileset: config/settings.ini and config/controls.ini, layered as built-in defaults, then the
//! copy beside the program, then the user's own copy under %LOCALAPPDATA%.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use eframe::egui::{Key, KeyboardShortcut, Modifiers};

pub const APP_ID: &str = "GenericCompany.DevConsole";
pub const SETTINGS: &str = "settings.ini";
pub const CONTROLS: &str = "controls.ini";
const DEFAULT_SETTINGS: &str = include_str!("../config/settings.ini");
const DEFAULT_CONTROLS: &str = include_str!("../config/controls.ini");

/// section -> key -> value
pub type Ini = BTreeMap<String, BTreeMap<String, String>>;

/// Parse `[section]` / `key = value` lines; `;` and `#` start comments. Later keys win.
pub fn parse(text: &str) -> Ini {
    let mut ini = Ini::new();
    let mut section = String::new();
    for raw in text.lines() {
        let line = raw.trim();
        if line.is_empty() || line.starts_with(';') || line.starts_with('#') {
            continue;
        }
        if let Some(name) = line.strip_prefix('[').and_then(|l| l.strip_suffix(']')) {
            section = name.trim().to_lowercase();
            continue;
        }
        if let Some((k, v)) = line.split_once('=') {
            ini.entry(section.clone()).or_default().insert(k.trim().to_lowercase(), v.trim().to_string());
        }
    }
    ini
}

/// Lay `over` on top of `base`, key by key.
pub fn merge(base: &mut Ini, over: Ini) {
    for (s, keys) in over {
        base.entry(s).or_default().extend(keys);
    }
}

/// Write `ini` back as text (used for the user's settings file).
pub fn render(ini: &Ini) -> String {
    let mut out = String::new();
    for (s, keys) in ini {
        out.push_str(&format!("[{s}]\n"));
        for (k, v) in keys {
            out.push_str(&format!("{k} = {v}\n"));
        }
        out.push('\n');
    }
    out
}

/// Parse `Ctrl+Shift+T`; None for an empty value. Err names what was not understood.
pub fn shortcut(text: &str) -> Result<Option<KeyboardShortcut>, String> {
    let text = text.trim();
    if text.is_empty() {
        return Ok(None);
    }
    let mut mods = Modifiers::NONE;
    let parts: Vec<&str> = text.split('+').map(str::trim).collect();
    // "Ctrl++" splits into ["Ctrl", "", ""]: the key is a literal plus.
    let (key_name, mod_names) = match parts.as_slice() {
        [m @ .., "", ""] => ("Plus", m),
        [m @ .., k] => (*k, m),
        [] => return Err(text.into()),
    };
    for m in mod_names {
        match m.to_lowercase().as_str() {
            "ctrl" | "control" | "cmd" => mods = mods | Modifiers::COMMAND | Modifiers::CTRL,
            "shift" => mods = mods | Modifiers::SHIFT,
            "alt" => mods = mods | Modifiers::ALT,
            _ => return Err(format!("unknown modifier '{m}' in '{text}'")),
        }
    }
    let key = Key::from_name(key_name)
        .or_else(|| Key::from_name(&key_name.to_uppercase()))
        .ok_or_else(|| format!("unknown key '{key_name}' in '{text}'"))?;
    Ok(Some(KeyboardShortcut::new(mods, key)))
}

pub struct Config {
    pub settings: Ini,
    pub controls: BTreeMap<String, KeyboardShortcut>,
    /// Problems found while reading, shown in the window.
    pub warnings: Vec<String>,
    pub user_dir: Option<PathBuf>,
}

impl Config {
    pub fn get(&self, section: &str, key: &str) -> Option<&str> {
        self.settings.get(section)?.get(key).map(String::as_str)
    }

    pub fn number(&self, section: &str, key: &str, fallback: f32) -> f32 {
        self.get(section, key).and_then(|v| v.parse().ok()).unwrap_or(fallback)
    }

    pub fn list(&self, section: &str, key: &str) -> Vec<String> {
        self.get(section, key)
            .map(|v| v.split(',').map(|s| s.trim().to_string()).filter(|s| !s.is_empty()).collect())
            .unwrap_or_default()
    }

    /// Save one setting to the user's settings.ini, keeping whatever else is there.
    pub fn save(&mut self, section: &str, key: &str, value: String) -> Result<(), String> {
        self.settings.entry(section.into()).or_default().insert(key.into(), value.clone());
        let dir = self.user_dir.clone().ok_or("no user folder")?;
        let path = dir.join(SETTINGS);
        let mut user = std::fs::read_to_string(&path).map(|t| parse(&t)).unwrap_or_default();
        user.entry(section.into()).or_default().insert(key.into(), value);
        std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
        std::fs::write(&path, render(&user)).map_err(|e| e.to_string())
    }
}

/// The user's config folder: `<LOCALAPPDATA>\Generic Company Inc\GenericCompany.DevConsole`.
pub fn user_dir(local_app_data: Option<&Path>) -> Option<PathBuf> {
    local_app_data.map(|d| d.join("Generic Company Inc").join(APP_ID))
}

/// Load the fileset from the layers in `dirs`, lowest priority first.
pub fn load(dirs: &[PathBuf], user: Option<PathBuf>) -> Config {
    let mut settings = parse(DEFAULT_SETTINGS);
    let mut controls_ini = parse(DEFAULT_CONTROLS);
    for d in dirs.iter().chain(user.iter()) {
        if let Ok(t) = std::fs::read_to_string(d.join(SETTINGS)) {
            merge(&mut settings, parse(&t));
        }
        if let Ok(t) = std::fs::read_to_string(d.join(CONTROLS)) {
            merge(&mut controls_ini, parse(&t));
        }
    }
    let mut controls = BTreeMap::new();
    let mut warnings = vec![];
    for (action, value) in controls_ini.remove("controls").unwrap_or_default() {
        match shortcut(&value) {
            Ok(Some(sc)) => {
                controls.insert(action, sc);
            }
            Ok(None) => {}
            Err(e) => warnings.push(format!("controls.ini {action}: {e}")),
        }
    }
    Config { settings, controls, warnings, user_dir: user }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_sections_comments_and_overrides() {
        let ini = parse("; c\n[View]\nZoom = 1.5\n# x\nzoom=2\n[live]\nskip = a, b\n");
        assert_eq!(ini["view"]["zoom"], "2");
        assert_eq!(ini["live"]["skip"], "a, b");
    }

    #[test]
    fn render_round_trips() {
        let ini = parse("[a]\nx = 1\n[b]\ny = two words\n");
        assert_eq!(parse(&render(&ini)), ini);
    }

    #[test]
    fn shortcuts_parse() {
        let sc = shortcut("Ctrl+Shift+T").unwrap().unwrap();
        assert_eq!(sc.logical_key, Key::T);
        assert!(sc.modifiers.shift && sc.modifiers.ctrl);
        assert_eq!(shortcut("Ctrl+Plus").unwrap().unwrap().logical_key, Key::Plus);
        assert_eq!(shortcut("Ctrl++").unwrap().unwrap().logical_key, Key::Plus);
        assert_eq!(shortcut("Ctrl+Minus").unwrap().unwrap().logical_key, Key::Minus);
        assert_eq!(shortcut("Ctrl+0").unwrap().unwrap().logical_key, Key::Num0);
        assert_eq!(shortcut("F5").unwrap().unwrap().logical_key, Key::F5);
        assert_eq!(shortcut("ctrl+l").unwrap().unwrap().logical_key, Key::L);
        assert!(shortcut("").unwrap().is_none());
        assert!(shortcut("Hyper+T").is_err());
        assert!(shortcut("Ctrl+Nope").is_err());
    }

    #[test]
    fn defaults_have_every_control_and_no_warnings() {
        let c = load(&[], None);
        assert!(c.warnings.is_empty(), "{:?}", c.warnings);
        for a in ["zoom_in", "zoom_out", "zoom_reset", "test_all", "test", "run", "toggle_live"] {
            assert!(c.controls.contains_key(a), "{a}");
        }
        assert_eq!(c.number("view", "zoom", 0.0), 1.0);
        assert!(c.list("live", "skip").contains(&"target".to_string()));
    }

    #[test]
    fn user_layer_overrides_and_save_persists() {
        let dir = std::env::temp_dir().join(format!("gc-console-cfg-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::write(dir.join(CONTROLS), "[controls]\ntest = F9\nrun =\nbuild = Bogus+X\n").unwrap();
        let mut c = load(&[], Some(dir.clone()));
        assert_eq!(c.controls["test"].logical_key, Key::F9);
        assert!(!c.controls.contains_key("run"));
        assert_eq!(c.warnings.len(), 1);
        c.save("view", "zoom", "1.3".into()).unwrap();
        let again = load(&[], Some(dir.clone()));
        assert_eq!(again.number("view", "zoom", 0.0), 1.3);
        std::fs::remove_dir_all(&dir).unwrap();
    }
}

// ==== stamp v1 | author=kjFriday | hmac-sha256=ffc62712c3edaeca8107a3e5aa2e987c10203bd96f94d5c2f601bc3486446814 ====
