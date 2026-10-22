
with open("whatsapp_service.py", "r", encoding="utf-8") as f:
    content = f.read()

# Check where handle_inbound_auto_response generates audio
if "generate_spoken_audio" in content and "is_voice" in content:
    print("Voice handling references exist in file.")

# Print the block where reply text is sent to WhatsApp
import re
idx = content.find("def handle_inbound_auto_response")
if idx != -1:
    sub_content = content[idx:idx+4500]
    lines = [line for line in sub_content.split("\n") if "send_" in line or "voice" in line or "audio" in line]
    print("Relevant dispatch lines:")
    for l in lines[:15]:
        print("  ", l.strip())

