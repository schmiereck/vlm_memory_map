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

# Ohne Kamera, mit AI2-THOR:

```
# Windows:
pip install "ai2thor==4.3.0"
# Linux:
pip install ai2thor
python main.py --gui --thor --scene FloorPlan1
```

# Beispiele für Anweisungen

* Suche die Magnetspiel-Struktur aus farbigen Stäben und Metall-Kugeln und fahre bis dicht vor sie hin.
* Locate the Magnetic-Toy structure build of colored rods and metal balls and drive until you are very close to it.

* Trage alle Objekte in Deiner Umgebung in die Karte ein und verschaffe Dir so einen Überblick über Deine Umgebung.
* Add all objects in your surroundings to the map to get an overview of your environment.


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
