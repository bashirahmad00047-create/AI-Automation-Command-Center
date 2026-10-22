
with open("whatsapp_service.py", "r", encoding="utf-8") as f:
    content = f.read()

# Let us find where incoming message type is checked and handle_inbound_auto_response is called
# We will inject is_voice=True whenever type is audioMessage, voiceMessage, or ptt
target_pattern = "handle_inbound_auto_response("
# Check occurrences
if target_pattern in content:
    print("Found handle_inbound_auto_response calls.")

