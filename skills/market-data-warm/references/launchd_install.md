# Installing the launchd cron job

The warm pipeline runs via macOS launchd — native, no daemons, survives reboots.
This document covers install, verification, and troubleshooting.

## One-time install

```bash
# 1. Copy the plist to LaunchAgents (use cp, not mv — keep the original in market_data/)
cp ~/.config/market_data/com.gary.market-data.warm.plist ~/Library/LaunchAgents/

# 2. Verify the plist is syntactically valid
plutil -lint ~/Library/LaunchAgents/com.gary.market-data.warm.plist
# expected output: "...com.gary.market-data.warm.plist: OK"

# 3. Load the job (modern syntax — replaces deprecated `launchctl load`)
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.gary.market-data.warm.plist

# 4. Confirm it's registered
launchctl list | grep market-data
# expected: <pid_or_-_> <last_exit_code> com.gary.market-data.warm
```

## Test the job runs correctly

```bash
# Manually kickstart (immediate run, doesn't wait for Saturday)
launchctl kickstart -k gui/$(id -u)/com.gary.market-data.warm

# Watch it run
tail -f ~/.config/market_data/warm.log

# Or check launchd's own stdout/stderr capture (useful for crashes)
tail -f ~/.config/market_data/logs/launchd.stdout.log
tail -f ~/.config/market_data/logs/launchd.stderr.log
```

A successful run ends with `══════════` divider lines and a `FINAL SUMMARY` block.

## Verify it'll fire on Saturday

```bash
launchctl print gui/$(id -u)/com.gary.market-data.warm | grep -A 4 'next start'
# example output:
#    next start = May 23 09:00:00 +0800 2026  (≈ next Saturday)
```

## Updating the plist (e.g. changing the schedule)

```bash
# 1. Unload
launchctl bootout gui/$(id -u)/com.gary.market-data.warm

# 2. Edit
$EDITOR ~/.config/market_data/com.gary.market-data.warm.plist

# 3. Re-copy
cp ~/.config/market_data/com.gary.market-data.warm.plist ~/Library/LaunchAgents/

# 4. Reload
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.gary.market-data.warm.plist
```

## Common timing reference

| Local time (HKT) | UTC | PT (winter) | PT (summer) |
|---|---|---|---|
| Sat 09:00 (default) | Sat 01:00 | Fri 17:00 | Fri 18:00 |
| Sat 06:00 | Fri 22:00 | Fri 14:00 | Fri 15:00 |
| Sun 02:00 | Sat 18:00 | Sat 10:00 | Sat 11:00 |

US markets close 16:00 PT (M-F). The default Sat 09:00 HKT is after US Friday close, giving the data a full settle cycle before the warm runs.

## Permanently uninstall

```bash
launchctl bootout gui/$(id -u)/com.gary.market-data.warm
rm ~/Library/LaunchAgents/com.gary.market-data.warm.plist
# (the original at ~/.config/market_data/ stays so you can reinstall)
```

## Troubleshooting

### "Service is disabled"
```bash
launchctl enable gui/$(id -u)/com.gary.market-data.warm
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.gary.market-data.warm.plist
```

### "Load failed: 5: Input/output error"
Usually a syntax error in the plist. Run `plutil -lint` to find it.

### The job runs but `warm.log` doesn't update
Most likely the Python venv path is wrong. Verify:
```bash
ls -l /Users/garyho/.config/market_data/venv/bin/python
# should resolve via the symlink to ~/.config/forward-rdcf/venv/bin/python
```
If broken, fix the venv symlink first.

### Job fires but exits with code 5/78/etc.
Read `~/.config/market_data/logs/launchd.stderr.log`. Common causes:
- `Module not found: tradingview_screener` → venv missing the package
- `Permission denied` → script not executable (`chmod +x ~/.config/market_data/warm_watchlist.py`)
- `ModuleNotFoundError: marketdata` → sys.path issue, shouldn't happen with the script's `_BASE` setup

### "Operation not permitted" when accessing files
macOS Privacy → Full Disk Access. Open System Settings → Privacy & Security → Full Disk Access, add Terminal (or whatever spawns launchctl). Usually unnecessary for files in `~/.config/`.

### The plist references your username explicitly
The current plist hardcodes `/Users/garyho/` paths. If you copy this skill to another machine, edit the plist's `ProgramArguments` and `StandardOutPath` / `StandardErrorPath` first.

## Why launchd over cron

macOS deprecated cron for user jobs years ago — it still works but doesn't run when the laptop is asleep, doesn't survive reboots cleanly, and has no good way to capture stdout/stderr. launchd handles all three: if your Mac is asleep at fire time, the job runs on next wake (within `StartCalendarInterval` semantics); after reboot, launchd loads enabled agents automatically; stdout/stderr go to the paths you specify.

The only downside vs cron is the verbose XML, but you only write it once.
