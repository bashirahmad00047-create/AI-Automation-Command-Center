
with open("whatsapp_service.py", "r", encoding="utf-8") as f:
    content = f.read()

# Let us check how handle_inbound_auto_response is called around audio message processing
# We will inject is_voice=True where audio types are parsed
print("Applying voice flag integration...")

