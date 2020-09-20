from time import sleep

class Pin:
  OUT = "out"
  IN = "in"

  def __init__(self, pin, direction):
    self.pin_num = pin
    self.direction = direction
    self.export()
    sleep(0.5)
    self.set_direction(direction)

  def export(self):
    try:
      with open("/sys/class/gpio/export", "w") as f:
        f.write("%d" % self.pin_num)
    except OSError as e:
      print("Export: GPIO %d is probably already exported. (%s)" % (self.pin_num, repr(e)))
      return False
    return True

  def set_direction(self, direction):
    with open("/sys/class/gpio/gpio%d/direction" % self.pin_num, "w") as f:
      f.write(direction)

  def value(self, val):
    with open("/sys/class/gpio/gpio%d/value" % self.pin_num, "w") as f:
      f.write(str(val))

  def get_value(self):
    with open("/sys/class/gpio/gpio%d/value" % self.pin_num, "r") as f:
      return int(f.read())