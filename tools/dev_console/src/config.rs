// ==== Generic Company Inc. portfolio ====================================
// Project: dev_console | File: src/config.rs
// About: The config fileset: config/settings.ini and config/controls.ini, layered as built-in...
// Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
// You may change this file under the AGPL-3.0. The stamp at the end marks
// the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
// ========================================================================

//! The config fileset: settings.ini, controls.ini and programs.ini, in layers.
//!
//! The three files are layered as built-in defaults (baked into the exe), then the copy beside the program,
//! then the user's own copy under %LOCALAPPDATA%. settings.ini and controls.ini merge key by key, so a user
//! file needs only the keys it changes; programs.ini is taken whole from the highest layer that has one,
//! since a program half from one file and half from another would make no sense. main.rs calls `load` at
//! start-up; app.rs reads settings with `number` and `list` and saves the text size with `save`; registry.rs
//! turns the programs section into programs.
//!
//! How `load` builds a `Config`:
//! 1. Parse the three built-in files.
//! 2. For each layer folder, lowest first, then the user folder: replace programs.ini if the folder has one,
//!    merge settings.ini and controls.ini over what is there.
//! 3. Turn each `[controls]` entry into a keyboard shortcut; one that does not parse becomes a warning, and
//!    an empty one means the control has no keys.
//!
//! The ini dialect is small on purpose: `[section]`, `key = value`, `;` or `#` comment lines; sections and keys
//! are case-insensitive. Defines `Ini` and `Config`.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use eframe::egui::{Key, KeyboardShortcut, Modifiers};

/// The console's id; it names the user's config folder under %LOCALAPPDATA%\Generic Company Inc.
pub const APP_ID: &str = "GenericCompany.DevConsole";
/// The file name of the general settings (text size, Live tests, live-production timings).
pub const SETTINGS: &str = "settings.ini";
/// The file name of the keyboard controls.
pub const CONTROLS: &str = "controls.ini";
/// The file name of the program list and each program's commands.
pub const PROGRAMS: &str = "programs.ini";
/// The shipped settings.ini, baked in with `include_str!` so the exe works with no config folder at all.
const DEFAULT_SETTINGS: &str = include_str!("../config/settings.ini");
/// The shipped controls.ini, baked in the same way; it names every control, so all keys work by default.
const DEFAULT_CONTROLS: &str = include_str!("../config/controls.ini");
/// The shipped programs.ini, baked in the same way; used when no layer has its own copy.
const DEFAULT_PROGRAMS: &str = include_str!("../config/programs.ini");

/// section -> key -> value
///
/// A BTreeMap keeps sections and keys sorted, so `render` writes them in a stable order.
pub type Ini = BTreeMap<String, BTreeMap<String, String>>;

/// Parse `[section]` / `key = value` lines; `;` and `#` start comments. Later keys win.
///
/// Never fails: blank lines, comment lines and lines with no `=` are skipped. Section and key names are
/// trimmed and lower-cased; values are trimmed but keep their case. Keys before the first section go in the
/// section named "". Only whole lines are comments, so a `;` inside a value stays part of it.
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
            ini.entry(section.clone())
                .or_default()
                .insert(k.trim().to_lowercase(), v.trim().to_string());
        }
    }
    ini
}

/// Lay `over` on top of `base`, key by key.
///
/// A key in `over` replaces the same key in `base`; keys only in `base` stay. Sections are created as needed.
pub fn merge(base: &mut Ini, over: Ini) {
    for (s, keys) in over {
        base.entry(s).or_default().extend(keys);
    }
}

/// Write `ini` back as text (used for the user's settings file).
///
/// Each section as `[name]`, its keys as `key = value`, then a blank line. Comments are not kept, since `parse`
/// drops them; `parse` reads the result back to the same `Ini`.
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
///
/// Steps:
/// 1. An empty value means "no keys" and is Ok(None), so a user can turn a control off with `name =`.
/// 2. Split on `+`. A trailing `++` means the key is the plus sign itself.
/// 3. Every part before the key is a modifier, in any case and order: Ctrl (also Control or Cmd), Shift, Alt.
///    Ctrl sets both egui's `ctrl` and `command`, so the shortcut matches whichever one egui reports on
///    Windows.
/// 4. The key is looked up by egui's name, as written and then upper-cased, so `l` works as well as `L`.
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

/// The loaded config: the merged settings, the parsed controls, the programs file and any problems.
///
/// Made once by `load` at start-up; app.rs owns it for the life of the window.
pub struct Config {
    /// settings.ini, merged over all layers.
    pub settings: Ini,
    /// Control name -> its keys; a control set to nothing in controls.ini is absent.
    pub controls: BTreeMap<String, KeyboardShortcut>,
    /// Problems found while reading, shown in the window.
    pub warnings: Vec<String>,
    /// The user's config folder, where `save` writes; None when LOCALAPPDATA is not set.
    pub user_dir: Option<PathBuf>,
    /// programs.ini from the highest layer that has one (the whole file, not merged key by key).
    pub programs: Ini,
    /// Where the programs editor saves: the file `programs` came from, or the first layer.
    pub programs_file: Option<PathBuf>,
}

// Reading settings, and saving one.
impl Config {
    /// The raw text of setting `key` in `section`, or None when either is missing.
    ///
    /// Both names must be lower case, as `parse` stores them.
    pub fn get(&self, section: &str, key: &str) -> Option<&str> {
        self.settings.get(section)?.get(key).map(String::as_str)
    }

    /// Setting `key` in `section` as a number, or `fallback` when it is missing or not a number.
    ///
    /// A typo in settings.ini therefore falls back to the default instead of stopping the console; callers
    /// clamp the result where a too-small value would do harm.
    pub fn number(&self, section: &str, key: &str, fallback: f32) -> f32 {
        self.get(section, key).and_then(|v| v.parse().ok()).unwrap_or(fallback)
    }

    /// Setting `key` in `section` as a comma-separated list, each item trimmed, empty items dropped.
    ///
    /// Empty when the setting is missing. Live tests use it for `[live] skip`.
    pub fn list(&self, section: &str, key: &str) -> Vec<String> {
        self.get(section, key)
            .map(|v| {
                v.split(',')
                    .map(|s| s.trim().to_string())
                    .filter(|s| !s.is_empty())
                    .collect()
            })
            .unwrap_or_default()
    }

    /// Save one setting to the user's settings.ini, keeping whatever else is there.
    ///
    /// Side effects: updates the setting in memory first (so it takes effect even if the write fails), then
    /// creates the user folder if needed and rewrites the user's file. Err says why (no user folder, or the
    /// file system error).
    ///
    /// Steps:
    /// 1. Set the value in the merged settings.
    /// 2. Read the user's own settings.ini (or start empty), not the merged settings: writing those would copy
    ///    every default into the user's file and freeze them there.
    /// 3. Set the one key, create the folder, write the file back.
    pub fn save(&mut self, section: &str, key: &str, value: String) -> Result<(), String> {
        self.settings
            .entry(section.into())
            .or_default()
            .insert(key.into(), value.clone());
        let dir = self.user_dir.clone().ok_or("no user folder")?;
        let path = dir.join(SETTINGS);
        let mut user = std::fs::read_to_string(&path).map(|t| parse(&t)).unwrap_or_default();
        user.entry(section.into()).or_default().insert(key.into(), value);
        std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
        std::fs::write(&path, render(&user)).map_err(|e| e.to_string())
    }
}

/// The user's config folder: `<LOCALAPPDATA>\Generic Company Inc\GenericCompany.DevConsole`.
///
/// `local_app_data` is passed in rather than read here, so tests can use any folder. None in gives None out.
pub fn user_dir(local_app_data: Option<&Path>) -> Option<PathBuf> {
    local_app_data.map(|d| d.join("Generic Company Inc").join(APP_ID))
}

/// Load the fileset from the layers in `dirs`, lowest priority first.
///
/// `user` is the user's config folder, read last so it wins; it is also where `save` writes. A missing file
/// in a layer is skipped without a warning. Never fails: problems end up in `warnings`.
///
/// Steps:
/// 1. Start from the built-in files. The programs file location starts as programs.ini in the first layer,
///    so the editor has somewhere to save even when no layer has one yet.
/// 2. Per layer, lowest first: a programs.ini replaces the programs whole and becomes the save location;
///    settings.ini and controls.ini merge key by key.
/// 3. Parse each `[controls]` entry: a shortcut is kept, an empty value leaves the control without keys,
///    and an error becomes a warning naming the control.
pub fn load(dirs: &[PathBuf], user: Option<PathBuf>) -> Config {
    let mut settings = parse(DEFAULT_SETTINGS);
    let mut controls_ini = parse(DEFAULT_CONTROLS);
    let mut programs = parse(DEFAULT_PROGRAMS);
    let mut programs_file = dirs.first().map(|d| d.join(PROGRAMS));
    for d in dirs.iter().chain(user.iter()) {
        if let Ok(t) = std::fs::read_to_string(d.join(PROGRAMS)) {
            programs = parse(&t);
            programs_file = Some(d.join(PROGRAMS));
        }
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
    Config {
        settings,
        controls,
        warnings,
        user_dir: user,
        programs,
        programs_file,
    }
}

/// Tests for the ini parser, the shortcut parser, the shipped defaults and the user layer.
#[cfg(test)]
mod tests {
    use super::*;

    /// Comments are skipped, names are lower-cased, and a later key overrides an earlier one.
    #[test]
    fn parse_sections_comments_and_overrides() {
        let ini = parse("; c\n[View]\nZoom = 1.5\n# x\nzoom=2\n[live]\nskip = a, b\n");
        assert_eq!(ini["view"]["zoom"], "2");
        assert_eq!(ini["live"]["skip"], "a, b");
    }

    /// Rendering and parsing again gives back the same sections, keys and values.
    #[test]
    fn render_round_trips() {
        let ini = parse("[a]\nx = 1\n[b]\ny = two words\n");
        assert_eq!(parse(&render(&ini)), ini);
    }

    /// Modifiers, Plus written as a word or as `++`, Minus, digits, function keys and lower case all parse;
    /// an empty value is no shortcut; an unknown modifier or key is an error.
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

    /// The built-in files alone load without warnings, name the main controls, and hold the expected
    /// settings.
    #[test]
    fn defaults_have_every_control_and_no_warnings() {
        let c = load(&[], None);
        assert!(c.warnings.is_empty(), "{:?}", c.warnings);
        for a in [
            "zoom_in",
            "zoom_out",
            "zoom_reset",
            "test_all",
            "test",
            "run",
            "toggle_live",
        ] {
            assert!(c.controls.contains_key(a), "{a}");
        }
        assert_eq!(c.number("view", "zoom", 0.0), 1.0);
        assert!(c.list("live", "skip").contains(&"target".to_string()));
    }

    /// A user controls.ini changes a key, clears another and reports a bad one; a saved setting is there on
    /// the next load. Uses a temporary folder named by process id and removes it.
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

// ==== stamp v1 | author=kjFriday | hmac-sha256=c719a8f0a4abb0c7193e6218ec32a5b137a04411a22a4371c3a6a5cc1086fec6 ====
