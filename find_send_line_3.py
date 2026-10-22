
with open("whatsapp_service.py", "r", encoding="utf-8") as f:
    content = f.read()

idx = content.find("def handle_inbound_auto_response")
if idx != -1:
    sub = content[idx+6500:idx+11000]
    lines = sub.split("\n")
    for i, line in enumerate(lines):
        if any(w in line.lower() for w in ["send", "reply", "dispatch", "audio", "voice", "green"]):
            print(f"Line {i}: {line.strip()}")

