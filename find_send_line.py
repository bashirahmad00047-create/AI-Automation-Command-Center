
with open("whatsapp_service.py", "r", encoding="utf-8") as f:
    content = f.read()

idx = content.find("def handle_inbound_auto_response")
if idx != -1:
    sub = content[idx:idx+4500]
    lines = sub.split("\n")
    for i, line in enumerate(lines):
        if "send" in line.lower() or "reply" in line.lower():
            print(f"Line {i}: {line.strip()}")

