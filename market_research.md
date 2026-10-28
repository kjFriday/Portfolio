# Market research: which projects could sell (2026-10)

Prices are third-party listings found 2026-10; check vendor pages before relying on them.

## Verdicts
| Project | Market | Gap | Verdict |
|---|---|---|---|
| install_wizard_maker | Inno Setup / NSIS free but script-based; Advanced Installer from **$499 one-time per user**, users complain about renewal fees ([Capterra](https://www.capterra.com/p/227766/Advanced-Installer), [GetApp](https://www.getapp.com/all-software/a/advanced-installer/)) | A simple GUI/JSON installer builder at $29–79 for indie devs | **Best bet** |
| drive_and_network_storage_manager | TreeSize Personal ~€20/yr, Professional ~€41/yr, network scanning only in Pro ([europeanpurpose](https://europeanpurpose.com/tool/treesize), [JAM editions](https://www.jam-software.com/treesize_free/editions.shtml)); WizTree, dupeGuru free | Zero-install single file + NAS/SMB share handling for small offices | Possible at ~$15–30 one-time; crowded |
| qr_code_studio (codec) | Commercial SDKs $599–$13,998 (Dynamsoft from $1,249, IronQR, Aspose) ([Capterra](https://www.capterra.com.au/software/178191/dynamsoft-barcode-reader-sdk), [HackerNoon](https://hackernoon.com/the-ultimate-c-qr-code-library-comparison-for-2026)); free ZXing/zbar/OpenCV exist | Pure-Python, dependency-free reader is rare, but likely slower/less robust than paid SDKs | Only if benchmarked against zbar; otherwise portfolio piece |
| Generic Company suite | Free/cheap incumbents for every category (CMS, tickets, CRUD) | None as-is | Don't sell; keep as portfolio |

## Before selling anything
- **License:** everything is AGPL-3.0. Offer a commercial license (dual-license) — allowed only where PROVENANCE.md shows reused code permits it.
- **Signing:** unsigned Windows exes trigger SmartScreen warnings; budget for a code-signing certificate.

## Demand and pain points (2026-10)
Web search returned no Reddit/HN threads; findings below come from AlternativeTo, review aggregators and forums. Samples are small.

### Wizard Maker
- Field is crowded: NSIS, WiX, Inno Setup (free); InstallForge, Setup Factory, DeployMaster, Basic Setup Builder (paid, "no script") ([AlternativeTo](https://alternativeto.net/software/inno-setup/?p=2)).
- Advanced Installer complaints: expensive licensing, steep learning curve, slow pre-sale support, Windows-only ([GetApp](https://www.getapp.co.uk/software/2053284/advanced-installer), [Capterra](https://www.capterra.com.au/reviews/1011001/advanced-installer)).
- **Pitch to test:** "one JSON file → signed setup.exe, no scripting, no MSI knowledge, $49 one-time". Its edge: zero-dependency Go, CI-friendly command line.

### Storage Manager
- Real demand for NAS duplicate scanning (Synology users with 100k+ files) ([Level1Techs](https://forum.level1techs.com/t/duplicate-file-finder/199227), [NASCompares](https://ask.nascompares.com/showthread.php?tid=8444)).
- Pain: scanning TBs over SMB takes days ([WinSCP forum](https://winscp.net/forum/viewtopic.php?p=57424)). Your same-size-first hashing helps; a measured "NAS TB scan" benchmark would be the selling point.
- Competitors: DupScout Pro/Ultimate (network shares), fclones (free, Rust) ([wingetgui](https://wingetgui.com/apps/Flexense-DupScoutPro), [changelog](https://changelog.com/news/bNwO)).
- TreeSize backlash: JAM moved to subscriptions, perpetual licenses now personal-only ([Ars via mirror](https://chat.macaw.me/community/news.movim.eu/ArsTechnica/urn-uuid-1f370f78-e316-5415-b606-7d7a55782cd8)). **Pitch:** "one-time price, no subscription, no install".

## Decision (2026-10-28)
Focus on **Storage Manager**. Wizard Maker is shelved for now.

## Recommendation
1. Lead with **Storage Manager**: clearer user pain (NAS + subscription fatigue) and non-developer buyers who pay. Benchmark a NAS scan against DupScout/fclones first.
2. Wizard Maker second: crowded and developer buyers lean free; sell only if a landing page gets signups.
3. Validate both with landing page + waitlist; post in r/DataHoarder, r/synology, r/homelab (Storage) and Show HN (Wizard).
