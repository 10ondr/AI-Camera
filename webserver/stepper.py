# Standard packages
from time import sleep

# Custom packages
from pin import Pin

class Stepper():
    def __init__(self, IN1, IN2, IN3, IN4, timeout):
        self.P1 = Pin(IN1, Pin.OUT)
        self.P2 = Pin(IN2, Pin.OUT)
        self.P3 = Pin(IN3, Pin.OUT)
        self.P4 = Pin(IN4, Pin.OUT)
        self.P1.value(0)
        self.P2.value(0)
        self.P3.value(0)
        self.P4.value(0)
        self.timeout = timeout

        self.stop = False
        self.turning = False
        self.command = None
        self.loop_running = False

    def step1(self):
        self.P4.value(1)
        sleep(self.timeout)
        self.P4.value(0)

    def step2(self):
        self.P4.value(1)
        self.P3.value(1)
        sleep(self.timeout)
        self.P4.value(0)
        self.P3.value(0)

    def step3(self):
        self.P3.value(1)
        sleep(self.timeout)
        self.P3.value(0)

    def step4(self):
        self.P2.value(1)
        self.P3.value(1)
        sleep(self.timeout)
        self.P2.value(0)
        self.P3.value(0)

    def step5(self):
        self.P2.value(1)
        sleep(self.timeout)
        self.P2.value(0)

    def step6(self):
        self.P1.value(1)
        self.P2.value(1)
        sleep(self.timeout)
        self.P1.value(0)
        self.P2.value(0)

    def step7(self):
        self.P1.value(1)
        sleep(self.timeout)
        self.P1.value(0)

    def step8(self):
        self.P4.value(1)
        self.P1.value(1)
        sleep(self.timeout)
        self.P4.value(0)
        self.P1.value(0)

    def set_stop(self):
        self.stop = True

    def set_command(self, cmd):
        self.command = cmd

    def right(self, step):
        self.stop = False
        self.turning = True
        for _ in range(step):
            if self.stop:
                break
            self.step1()
            self.step2()
            self.step3()
            self.step4()
            self.step5()
            self.step6()
            self.step7()
            self.step8()
        self.turning = False

    def left(self, step):
        self.stop = False
        self.turning = True
        for _ in range(step):
            if self.stop:
                break
            self.step8()
            self.step7()
            self.step6()
            self.step5()
            self.step4()
            self.step3()
            self.step2()
            self.step1()
            self.turning = False

    def start_loop(self):
        self.loop_running = True
        while self.loop_running:
            if self.command:
                while self.turning:
                    sleep(0.15)
                if self.command.startswith("R "):
                    self.right(int(self.command.split()[1]))
                elif self.command.startswith("L "):
                    self.left(int(self.command.split()[1]))
                self.command = None
            sleep(0.3)
    
    def stop_loop(self):
        self.loop_running = False