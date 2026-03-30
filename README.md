# VLM Memory Map

https://claude.ai/chat/d495fcd8-68d5-4c05-9110-fef171fc7761

pip install -r requirements.txt
export GROQ_API_KEY="gsk_..."

# Mit GUI (empfohlen):
python main.py --gui

# Ohne Kamera, mit Testbild:
python main.py --gui --image test.jpg

# Nur Terminal:
python main.py

Für den echten Roboter später:
Nur eine Zeile in main.py ändern:
python# Vorher:
robot = ConsoleRobotClient()
# Nachher:
robot = Ros2RobotClient()
