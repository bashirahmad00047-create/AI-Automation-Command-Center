
with open("whatsapp_service.py", "r", encoding="utf-8") as f:
    content = f.read()

import re

# Inspect all occurrences of handle_inbound_auto_response call
matches = [m.start() for m in re.finditer(r"handle_inbound_auto_response\(", content)]
print(f"Found {len(matches)} calls to handle_inbound_auto_response.")

for idx, pos in enumerate(matches):
    snippet = content[max(0, pos-150):min(len(content), pos+250)]
    print(f"\n--- Call #{idx+1} Snippet ---")
    print(snippet)

