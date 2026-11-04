# ==== Generic Company Inc. portfolio ====================================
# Project: portfolio | File: tools/verify.ps1
# About: End-to-end check of the six Generic Company programs against one sandbox database...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

# End-to-end check of the six Generic Company programs against one sandbox database.
# The database and every output stay in $Sandbox, which is emptied first. Builds the Go exes itself;
# build the Rust ones first (cargo build --release --features desktop):
#   powershell -ExecutionPolicy Bypass -File tools\verify.ps1
#
# The six programs share one SQLite file, generic_company.db. This script:
#   1. builds the two Go programs (CMS, notify hub) into $Sandbox\bin,
#   2. seeds a fresh database with the CRUD hub's seed.py,
#   3. opens each program's window once in --smoke mode, which writes a JSON report and exits,
#      and checks the report against the database,
#   4. makes the programs talk through the file: the doc pipeline registers an event, the hub's
#      count sees it, and the notify dispatcher drains pending events (a second pass changes nothing),
#   5. renames the database to prove no program still holds it open.
# Each check prints "ok" or "FAIL"; the exit code is 1 when any check failed.
# Needs python, go and the Rust release builds on hand; the Python programs run from the repo.
param([string]$Sandbox = (Join-Path $env:TEMP "generic-company-verify"))
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Remove-Item -Recurse -Force $Sandbox -ErrorAction SilentlyContinue
New-Item -ItemType Directory $Sandbox | Out-Null
$db = Join-Path $Sandbox "generic_company.db"
$hub = Join-Path $root "company\crud_hub"
$failed = 0
# Check prints one result line; a false $ok counts a failure in the script-wide $failed.
function Check($what, $ok) {
  if ($ok) { Write-Host "  ok    $what" } else { Write-Host "  FAIL  $what"; $script:failed++ }
}
# Rows counts rows of $table matching the SQL condition $where, through Python's sqlite3 module
# (no sqlite3 command-line tool is assumed). The names are spliced into the SQL text, which is fine
# for the fixed names this script passes.
function Rows($table, $where = "1") {
  [int](python -c "import sqlite3,sys; print(sqlite3.connect(sys.argv[1]).execute('SELECT COUNT(*) FROM ' + sys.argv[2] + ' WHERE ' + sys.argv[3]).fetchone()[0])" $db $table $where)
}
# Smoke runs one program with --db and --smoke, waits for it to exit, and returns its JSON report.
# The report has the window title, whether the icon was set, the data source ("db" when read from
# the database), the version and row counts. Start-Process joins arguments with spaces and does not
# quote them, so every path is wrapped in literal quotes. The version must be 0.2.0.
function Smoke($name, $exe, [string[]]$extra) {
  $out = Join-Path $Sandbox "$name.json"
  Start-Process -Wait -FilePath $exe -ArgumentList ($extra + @("--db", "`"$db`"", "--smoke", "`"$out`"", "--quiet")) | Out-Null
  $r = Get-Content $out -Encoding UTF8 | ConvertFrom-Json
  Check "$name window: '$($r.title)', icon $($r.icon_set), source $($r.source)" ($r.icon_set -and $r.source -eq "db" -and $r.version -eq "0.2.0")
  $r
}

# --- build --------------------------------------------------------------------------------------
# GOTOOLCHAIN=local: use the installed Go, never download another; CGO_ENABLED=0: pure Go, no C compiler.
# -H windowsgui marks the exe as a GUI program, so no console window opens with it.
"Building the Go programs"
$bin = Join-Path $Sandbox "bin"
$env:GOTOOLCHAIN = "local"; $env:CGO_ENABLED = "0"
go -C (Join-Path $root "company\journal") build -ldflags "-H windowsgui" -o (Join-Path $bin "generic-company-cms.exe") .
go -C (Join-Path $root "company\notify_hub") build -ldflags "-H windowsgui" -o (Join-Path $bin "generic-company-notify.exe") ./cmd/notify

# --- seed ---------------------------------------------------------------------------------------
# the starting counts are kept so later checks can see exactly what the programs changed
"Seeding $db"
python (Join-Path $hub "seed.py") --fresh --db $db | Out-Null
$docs0, $events0, $pending0 = (Rows documents), (Rows events), (Rows events "status = 'pending'")

# --- one window per program ---------------------------------------------------------------------
"Windows"
$h = Smoke "hub" "python" @("`"$(Join-Path $hub 'main.py')`"")
Check "hub counts match the file" ($h.counts.orders -eq (Rows orders) -and $h.counts.tickets -eq (Rows tickets))
$d = Smoke "docpipe" "python" @("`"$(Join-Path $root 'company\doc_pipeline\docpipe_app.py')`"", "--out", "`"$(Join-Path $Sandbox 'docs')`"")
Check "doc pipeline read 400 orders" ($d.counts.orders -eq 400)
$c = Smoke "cms" (Join-Path $bin "generic-company-cms.exe") @()
Check "CMS authors from the database" ($c.counts.authors -eq (Rows employees))
$n = Smoke "notify" (Join-Path $bin "generic-company-notify.exe") @()
$t = Smoke "tickets" (Join-Path $root "company\ticket_tracker\target\release\generic-company-tickets.exe") @()
Check "tracker shows every ticket" ($t.counts.shown -eq (Rows tickets))
$s = Smoke "dash" (Join-Path $root "company\data_dash\target\release\generic-company-dash.exe") @()

# --- programs talking through the file ----------------------------------------------------------
# docpipe adds one documents.generated event; dispatch then sends pending events to files in
# $Sandbox\outbox, and running it again must find nothing new to send
"Programs talking through the file"
Push-Location (Join-Path $root "company\doc_pipeline")
python -m docpipe --cli --db $db --out (Join-Path $Sandbox "docs") --register | Out-Null
Pop-Location
Check "docpipe registered a documents.generated event" ((Rows events "kind = 'documents.generated'") -eq 1)
Check "hub sees it: events $events0 -> $(Rows events)" ((Rows events) -eq $events0 + 1)
Push-Location (Join-Path $root "company\notify_hub")
go run ./cmd/dispatch -db $db -out (Join-Path $Sandbox "outbox") | Out-Null
$after1 = Rows events "status = 'pending'"
go run ./cmd/dispatch -db $db -out (Join-Path $Sandbox "outbox") | Out-Null
$after2 = Rows events "status = 'pending'"
Pop-Location
Check "dispatch: pending $pending0 -> $after1, second pass -> $after2 (no change)" ($after1 -lt $pending0 -and $after2 -eq $after1)

# --- no open handles ----------------------------------------------------------------------------
# Windows refuses to rename a file another process holds open without delete sharing (SQLite opens
# it that way), and with "Stop" a failed rename ends the script, so reaching the Check means every
# program closed the database
"Nothing left holding the file"
Rename-Item $db "generic-company-moved.db"; Rename-Item (Join-Path $Sandbox "generic-company-moved.db") "generic_company.db"
Check "generic_company.db can be renamed with every program closed" $true

if ($failed) { "$failed check(s) failed"; exit 1 } else { "All checks passed." }

# ==== stamp v1 | author=kjFriday | hmac-sha256=99b87999d9b7a6c55e319d2744e8010415de56b0560d0eb5e09063e70753d8a2 ====
