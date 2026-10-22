
with open("whatsapp_service.py", "r", encoding="utf-8") as f:
    content = f.read()

idx = content.find("def handle_inbound_auto_response")
if idx != -1:
    sub = content[idx+3000:idx+7000]
    lines = sub.split("\n")
    for i, line in enumerate(lines):
        if any(w in line.lower() for w in ["send", "reply", "api", "message"]):
            print(f"Line {i}: {line.strip()}")

