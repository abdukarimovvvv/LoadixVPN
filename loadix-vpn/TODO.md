# TODO - Fix unlimited traffic symbol display

## Task
Replace "0 GB" display with "♾ безлимит" symbol in the Telegram bot status section

## Files to Edit

### 1. loadix-vpn/bot/bot/handlers/status.py
- **Current**: `f"{_human_bytes(used_bytes)} / {sub['traffic_limit_gb']} GB"` shows "0 GB" for unlimited
- **Fix**: Add condition to show "♾ безлимит" when traffic_limit_gb is 0
- **Status**: ✅ Complete

### 2. loadix-vpn/bot/bot/handlers/admin.py
- **Status**: Already uses "♾ безлимит" - verified ✓ (no changes needed)

## Progress
- [x] Read status.py - identified line to edit
- [x] Read admin.py - confirmed already has unlimited symbol
- [x] Edit status.py to add unlimited check - DONE

## Files Updated
- status.py: Added condition to check traffic_limit_gb and display "♾ безлимит" instead of "0 GB"
