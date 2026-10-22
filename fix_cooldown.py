
with open("whatsapp_service.py", "r", encoding="utf-8") as f:
    content = f.read()

# Replace cooldown checking logic to always be 0 (no cooldown restriction)
old_line = "cooldown_mins = auto_conf.get(\"cooldown_minutes\", 0)"
new_line = "cooldown_mins = 0  # Force zero cooldown for all inbound messages"

if old_line in content:
    content = content.replace(old_line, new_line)
    with open("whatsapp_service.py", "w", encoding="utf-8") as f:
        f.write(content)
    print("SUCCESS: Cooldown timer disabled! All friends and customers will now get immediate auto-responses.")
else:
    print("WARNING: Exact line not matched, searching with regex...")
    import re
    content = re.sub(r"cooldown_mins\s*=\s*auto_conf\.get\(.*?\)", "cooldown_mins = 0", content)
    with open("whatsapp_service.py", "w", encoding="utf-8") as f:
        f.write(content)
    print("SUCCESS: Updated cooldown_mins to 0 via regex!")

