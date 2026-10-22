
with open("whatsapp_service.py", "r", encoding="utf-8") as f:
    content = f.read()

# Let us check around line 1575 or search for empty else block
import re

# Fix trailing empty else: statements or fix indentation
lines = content.split("\n")
new_lines = []
for i, line in enumerate(lines):
    new_lines.append(line)
    if line.strip() == "else:" and (i + 1 < len(lines)) and (lines[i+1].strip() == "" or not lines[i+1].startswith(" ")):
        # add a pass statement if else is empty
        indent = len(line) - len(line.lstrip()) + 4
        new_lines.append(" " * indent + "pass")

fixed_content = "\n".join(new_lines)
with open("whatsapp_service.py", "w", encoding="utf-8") as f:
    f.write(fixed_content)

print("Indentation and empty else blocks fixed successfully!")

