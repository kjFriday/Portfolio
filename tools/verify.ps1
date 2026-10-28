# ==== Generic Company Inc. portfolio ====================================
# Project: portfolio | File: tools/verify.ps1
# About: ==== Generic Company Inc. portfolio ===============================================...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
# ========================================================================

# ==== Generic Company Inc. portfolio ===============================================
# Project: portfolio | File: tools/verify.ps1
# About: End-to-end check of the six Generic Company programs against one sandbox database (nothing outside...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
# ========================================================================

# End-to-end check of the six Generic Company programs against one sandbox database (nothing outside $Sandbox is
# touched). Builds the Go exes itself; build the Rust ones first (cargo build --release --features desktop):
#   powershell -ExecutionPolicy Bypass -File tools\verify.ps1
param([string]$Sandbox = (Join-Path $env:TEMP "generic-company-verify"))
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Remove-Item -Recurse -Force $Sandbox -ErrorAction SilentlyContinue
New-Item -ItemType Directory $Sandbox | Out-Null
$db = Join-Path $Sandbox "generic_company.db"
$hub = Join-Path $root "create_read_update_delete_simple_io_data_base"
$failed = 0
function Check($what, $ok) {
  if ($ok) { Write-Host "  ok    $what" } else { Write-Host "  FAIL  $what"; $script:failed++ }
}
function Rows($table, $where = "1") {
  [int](python -c "import sqlite3,sys; print(sqlite3.connect(sys.argv[1]).execute('SELECT COUNT(*) FROM ' + sys.argv[2] + ' WHERE ' + sys.argv[3]).fetchone()[0])" $db $table $where)
}
function Smoke($name, $exe, [string[]]$extra) {
  $out = Join-Path $Sandbox "$name.json"
  Start-Process -Wait -FilePath $exe -ArgumentList ($extra + @("--db", "`"$db`"", "--smoke", "`"$out`"", "--quiet")) | Out-Null
  $r = Get-Content $out -Encoding UTF8 | ConvertFrom-Json
  Check "$name window: '$($r.title)', icon $($r.icon_set), source $($r.source)" ($r.icon_set -and $r.source -eq "db" -and $r.version -eq "0.2.0")
  $r
}

"Building the Go programs"
$bin = Join-Path $Sandbox "bin"
$env:GOTOOLCHAIN = "local"; $env:CGO_ENABLED = "0"
go -C (Join-Path $root "content_management_system") build -ldflags "-H windowsgui" -o (Join-Path $bin "generic-company-cms.exe") .
go -C (Join-Path $root "notification_and_message_hub") build -ldflags "-H windowsgui" -o (Join-Path $bin "generic-company-notify.exe") ./cmd/notify

"Seeding $db"
python (Join-Path $hub "seed.py") --fresh --db $db | Out-Null
$docs0, $events0, $pending0 = (Rows documents), (Rows events), (Rows events "status = 'pending'")

"Windows"
$h = Smoke "hub" "python" @("`"$(Join-Path $hub 'main.py')`"")
Check "hub counts match the file" ($h.counts.orders -eq (Rows orders) -and $h.counts.tickets -eq (Rows tickets))
$d = Smoke "docpipe" "python" @("`"$(Join-Path $root 'document_mover_and_changer\docpipe_app.py')`"", "--out", "`"$(Join-Path $Sandbox 'docs')`"")
Check "doc pipeline read 400 orders" ($d.counts.orders -eq 400)
$c = Smoke "cms" (Join-Path $bin "generic-company-cms.exe") @()
Check "CMS authors from the database" ($c.counts.authors -eq (Rows employees))
$n = Smoke "notify" (Join-Path $bin "generic-company-notify.exe") @()
$t = Smoke "tickets" (Join-Path $root "simple_ticket_tracker\target\release\generic-company-tickets.exe") @()
Check "tracker shows every ticket" ($t.counts.shown -eq (Rows tickets))
$s = Smoke "dash" (Join-Path $root "data_dash\target\release\generic-company-dash.exe") @()

"Programs talking through the file"
Push-Location (Join-Path $root "document_mover_and_changer")
python -m docpipe --cli --db $db --out (Join-Path $Sandbox "docs") --register | Out-Null
Pop-Location
Check "docpipe registered a documents.generated event" ((Rows events "kind = 'documents.generated'") -eq 1)
Check "hub sees it: events $events0 -> $(Rows events)" ((Rows events) -eq $events0 + 1)
Push-Location (Join-Path $root "notification_and_message_hub")
go run ./cmd/dispatch -db $db -out (Join-Path $Sandbox "outbox") | Out-Null
$after1 = Rows events "status = 'pending'"
go run ./cmd/dispatch -db $db -out (Join-Path $Sandbox "outbox") | Out-Null
$after2 = Rows events "status = 'pending'"
Pop-Location
Check "dispatch: pending $pending0 -> $after1, second pass -> $after2 (no change)" ($after1 -lt $pending0 -and $after2 -eq $after1)

"Nothing left holding the file"
Rename-Item $db "generic-company-moved.db"; Rename-Item (Join-Path $Sandbox "generic-company-moved.db") "generic_company.db"
Check "generic_company.db can be renamed with every program closed" $true

if ($failed) { "$failed check(s) failed"; exit 1 } else { "All checks passed." }

# ==== stamp v1 | author=kjFriday | hmac-sha256=c35c56ce6d3d9d510e2177a91fc55293c2f2e85c63f99d04838b38d26f03289f ====
