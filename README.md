# VLM Memory Map

```
pip install -r requirements.txt
export GROQ_API_KEY="gsk_..."
```

# Mit GUI (empfohlen):
```
python main.py --gui
```

# Ohne Kamera, mit Testbild:
```
python main.py --gui --image test.jpg
python main.py --gui --image test3.jpg
python main.py --gui --image test4.jpg
```

Suche die Magnetspiel-Struktur aus farbigen Stäben und Metall-Kugeln und fahre bis dicht vor sie hin.

# Nur Terminal:
```
python main.py
```

Für den echten Roboter später:
Nur eine Zeile in main.py ändern:
```
python# Vorher:
robot = ConsoleRobotClient()
# Nachher:
robot = Ros2RobotClient()
```
