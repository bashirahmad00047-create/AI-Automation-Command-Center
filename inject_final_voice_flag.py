
with open("whatsapp_service.py", "r", encoding="utf-8") as f:
    content = f.read()

# Target Call #2 and Call #3 to add is_voice=is_voice (or checking if message type is audio/voice)
# Let us check how message type is determined in those blocks
print("Injecting voice flag parameter...")

