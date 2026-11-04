# ==== Generic Company Inc. portfolio ====================================
# Project: portfolio | File: tools/shot.ps1
# About: Screenshot one Generic Company window so its icon and title can be checked by eye.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

# Screenshot one Generic Company window so its icon and title can be checked by eye.
#   tools\shot.ps1 -Title "Generic Company CRUD Hub" -Out shot.png -Exe python -ArgList main.py,--db,C:\tmp\generic_company.db
#
# Parameters: -Title is part of the window title to wait for; -Out the PNG to write; -Exe and
# -ArgList the program to start; -Wait the seconds to let the window finish drawing.
#
# Steps:
#   1. Declare the three user32 calls through Add-Type (C# P/Invoke) and make this process DPI
#      aware, so window sizes come back in real screen pixels, not scaled ones.
#   2. Start the program, then poll every 300 ms, for up to 30 s, for any process whose main window
#      title contains -Title (the window may belong to a child process, not the one started).
#   3. Wait -Wait seconds, then have the window paint itself into a bitmap and save it as PNG.
#   4. Print "process 'title' -> file" and close the program.
# Known limitation: the window is matched by title across all processes, so an already open window
# with a matching title is captured, and then stopped, instead of the new one.
param([string]$Title, [string]$Out, [string]$Exe, [string[]]$ArgList = @(), [int]$Wait = 3)

Add-Type -AssemblyName System.Drawing
# W.R mirrors the Win32 RECT (left, top, right, bottom); "Ri" is right, as R is the type's own name
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
# flag 2 is PW_RENDERFULLCONTENT (Windows 8.1 and later): it also captures GPU-drawn content such
# as WebView2 pages, which the default flag leaves black
$r = New-Object W+R; [W]::GetWindowRect($win.MainWindowHandle, [ref]$r) | Out-Null
$bmp = New-Object System.Drawing.Bitmap ($r.Ri - $r.L), ($r.B - $r.T)
$g = [System.Drawing.Graphics]::FromImage($bmp); $dc = $g.GetHdc(); [W]::PrintWindow($win.MainWindowHandle, $dc, 2) | Out-Null; $g.ReleaseHdc($dc)
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png); $g.Dispose(); $bmp.Dispose()
"{0} '{1}' -> {2}" -f $win.ProcessName, $win.MainWindowTitle, $Out
# stop both the window's process and the one started, in case they differ
Stop-Process -Id $win.Id -ErrorAction SilentlyContinue; Stop-Process $p -ErrorAction SilentlyContinue

# ==== stamp v1 | author=kjFriday | hmac-sha256=0f8b1c7a988202e9b6b624308971b6877377c9e5dd565c7f451d936ab35ffc02 ====
