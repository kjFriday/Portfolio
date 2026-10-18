# ==== ACME Inc. portfolio ===============================================
# Project: portfolio | File: tools/shot.ps1
# About: Screenshot one ACME window for checking icons and titles by eye: tools\shot.ps1 -Title...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
# ========================================================================

# Screenshot one ACME window for checking icons and titles by eye:
#   tools\shot.ps1 -Title "ACME CRUD Hub" -Out shot.png -Exe python -ArgList main.py,--db,C:\tmp\acme.db
param([string]$Title, [string]$Out, [string]$Exe, [string[]]$ArgList = @(), [int]$Wait = 3)

Add-Type -AssemblyName System.Drawing
Add-Type @"
using System; using System.Runtime.InteropServices;
public static class W {
  [StructLayout(LayoutKind.Sequential)] public struct R { public int L, T, Ri, B; }
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out R r);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint flags);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
}
"@
[W]::SetProcessDPIAware() | Out-Null
$p = Start-Process -FilePath $Exe -ArgumentList $ArgList -PassThru
$deadline = (Get-Date).AddSeconds(30); $win = $null
while (-not $win -and (Get-Date) -lt $deadline) {
  Start-Sleep -Milliseconds 300
  $win = Get-Process | Where-Object { $_.MainWindowTitle -like "*$Title*" } | Select-Object -First 1
}
if (-not $win) { Stop-Process $p -ErrorAction SilentlyContinue; throw "no window titled *$Title*" }
Start-Sleep -Seconds $Wait
# PrintWindow renders the window itself, so other windows on top (or focus) do not matter
$r = New-Object W+R; [W]::GetWindowRect($win.MainWindowHandle, [ref]$r) | Out-Null
$bmp = New-Object System.Drawing.Bitmap ($r.Ri - $r.L), ($r.B - $r.T)
$g = [System.Drawing.Graphics]::FromImage($bmp); $dc = $g.GetHdc(); [W]::PrintWindow($win.MainWindowHandle, $dc, 2) | Out-Null; $g.ReleaseHdc($dc)
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png); $g.Dispose(); $bmp.Dispose()
"{0} '{1}' -> {2}" -f $win.ProcessName, $win.MainWindowTitle, $Out
Stop-Process -Id $win.Id -ErrorAction SilentlyContinue; Stop-Process $p -ErrorAction SilentlyContinue

# ==== stamp v1 | author=kjFriday | hmac-sha256=802b90e79419911b70b86b2a06579b540805af5d68496cd8f1c4310a06568aa3 ====
