#!/usr/bin/python3

# Standard packages
import io
import logging
import socketserver
import socket
import threading
from http import server
from os import curdir, sep
import subprocess
from time import sleep, monotonic, strftime
import json

# Raspberry Pi specific packages
import picamera

# Custom packages
from pin import Pin
from stepper import Stepper

# Project directory (root directory of the project structure)
project_path = "/home/pi"

# Config JSON file
config_path = project_path + "/webserver/config.json"

# Mode of operation
operation_mode = "object_detection_with_PIR"

# Timelapse
timelapse_timeout = 5 # seconds
timelapse_running = False

### SSH config ###
ssh_address = "your.ssh.address.here" # Remote server that accepts SSH connections
ssh_username = "your_ssh_username"    # Username for SSH connection
ssh_password = "your_ssh_password_here" # For creating SSH connections automatically using sshpass (without using RSA keys)
# First SSH tunnel
ssh_port_webserver = 9998   # Port used for one reverse SSH tunnel (webserver)
ssh_local_port_webserver = ssh_port_webserver # I'll use the same port on both ends of the tunnel
# Second SSH tunnel
ssh_port_socket = 9999      # Port used for the second reverse SSH tunnel (socket for replies)
ssh_local_port_socket = ssh_port_socket # I'll use the same port on both ends of the tunnel

# Backend command to run on the remote server (to start the Tensorflow session)
# For me it is somethig like this: "cd /home/<my_username>/secret/tensorflow/models/research/object_detection && taskset -c 1-8 ./object_detection_backend.py > /dev/null 2>&1"
backend_command = "your_backend_command"

### Object detection config ###
# Remote config
object_detection_targets = list() # String list of objects to detect
min_score_thresh = 40 # The result will be sent if the classifier is at least this % sure it detected the specified object
# Local config
min_width_thres = 20 # [% of the image width] When the object is at least this far from the center, the device will adjust it's angle (will turn)
record_video = False
capture_still = False

# Camera video recording config (main camera config)
rec_resolution = (1920, 1080)
rec_fps = 30
rec_format = "h264"
rec_rotation = 180
rec_splitter_port = 1
is_recording = False
record_until_idle_timestamp = monotonic()

# Camera still capture config
cap_resolution = (1920, 1080) # Equal or smaller than rec_resolution
cap_format = "jpeg"
cap_splitter_port = 2

# Camera stream config
stream_resolution = (640, 360) # Equal or smaller than rec_resolution
stream_bitrate = 5000000
stream_fps = 3
stream_splitter_port = 3

# Webserver
g_camera = None
g_output = None
g_server = None
stream_enabled = True
webserver_restart = True

# Stepper
pin_IN1 = 15
pin_IN2 = 18
pin_IN3 = 4
pin_IN4 = 17
pulse_timeout = 0.001 # time to wait before sending another pulse to the stepper motor (smaller = faster but less strong and less precise)
stepper = Stepper(pin_IN1, pin_IN2, pin_IN3, pin_IN4, pulse_timeout)

# PIR sensors
IR_PIN = 23
IR2_PIN = 27
IR_front = Pin(IR_PIN, Pin.IN)
IR_back = Pin(IR2_PIN, Pin.IN)
IR_timestamp = monotonic()
IR_time_threshold = 15 # seconds before subsequent IR input is recognized again
IR_loop_running = False

# Processes object detection results and calculates if the device should adjust its rotation or not
def process_coords(data):
    im_width = stream_resolution[0]
    prioritized_target = None
    targets = data["tar"]
    for target in targets:
        if not prioritized_target:
            prioritized_target = target
        else:
            if object_detection_targets.index(target["n"]) < object_detection_targets.index(prioritized_target["n"]):
                prioritized_target = target
    left = int(prioritized_target["l"])
    right = int(prioritized_target["r"])
    x_center = left + ((right - left) / 2)
    x_len = im_width / 2 - x_center
    x_len_abs = abs(x_len)
    if x_len_abs > im_width * (min_width_thres / 100):
        move = (x_len_abs / im_width) * 77.1 # 77.1 is move across 54 degrees (camera FOV)
        if x_len > 0:
            stepper.set_command("L %d" % move)
        else:
            stepper.set_command("R %d" % move)

# Creates two reverse SSH tunnels on different ports by using the ssh address, login and password
def create_ssh_tunnels():
    subprocess.Popen(["sshpass", "-p", ssh_password, "ssh", "-oStrictHostKeyChecking=no", "-N", "-R", "%s:localhost:%s" % (ssh_port_webserver, ssh_local_port_webserver), "%s@%s" % (ssh_username, ssh_address)])
    subprocess.Popen(["sshpass", "-p", ssh_password, "ssh", "-oStrictHostKeyChecking=no", "-N", "-R", "%s:localhost:%s" % (ssh_port_socket, ssh_local_port_socket), "%s@%s" % (ssh_username, ssh_address)])

# Starts a new thread with the stepper motor loop which will process commands and rotate the device
def start_stepper():
    def inner():
        print("Stepper: Thread started...")
        stepper.start_loop()
    thread_stepper = threading.Thread(target=inner)
    thread_stepper.start()

# Starts a new thread with the socket listening to the remote replies (object detection results)
def start_receiver():
    def inner():
        print("Remote receiver: Thread started...")
        sock_recv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock_recv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock_recv.bind(('', ssh_local_port_socket))
        sock_recv.listen(5)
        while True:
            print("Remote receiver: Listening for a new connection...")
            connection, address = sock_recv.accept()
            print("Remote receiver: Client connected!", address)
            while True:
                try:
                    buf = connection.recv(1024)
                    if not buf:
                        print("Remote receiver: buf is empty, breaking while loop")
                        break
                    if len(buf) > 0:
                        buf = buf.decode('UTF-8').strip()
                        print("Remote receiver:", buf)
                        if buf == "ready":
                            print("Remote server ready, sending config...")
                            response_data = { "min_score_thresh": min_score_thresh,
                                               "targets": object_detection_targets
                                            }
                            connection.send(json.dumps(response_data).encode(encoding='UTF-8'))
                        else:
                            json_array = buf.strip().split()
                            for json_record in reversed(json_array):
                                try:
                                    process_coords(json.loads(json_record))
                                    if capture_still:
                                        take_photo(project_path + "/footage/photos/" + get_string_time())
                                    if record_video:
                                        record_until_idle(project_path + "/footage/videos/" + get_string_time())
                                except json.decoder.JSONDecodeError:
                                    print("JSON parse error, skipping record...")
                except Exception as e:
                    print(repr(e))

    thread_receiver = threading.Thread(target=inner)
    thread_receiver.start()

# Kills a backend Tensorflow object detection script by closing the SSH connection created with a -tt
def kill_backend():
    print("Killing backend connection...")
    p = subprocess.Popen(["pkill", "-f", "ssh -tt"])
    p.wait()
    if p.returncode == 0:
        print("Previous backend connection killed successfully")

# Runs a provided command on the remote server (starts the object detection script remotely)
def run_backend(remote_cmd):
    print("Starting backend...")
    p = subprocess.Popen(["sshpass", "-p", ssh_password, "ssh", "-oStrictHostKeyChecking=no", "-tt", "%s@%s" % (ssh_username, ssh_address), remote_cmd])

# Process and load the HTML index page from file
def load_index_page():
    global PAGE
    with open(project_path + "/webserver/index.html", "r") as f_index:
        PAGE = f_index.read()
        with open(config_path, "r") as f_config:
            PAGE = PAGE % f_config.read()

# Load config from JSON file
# TODO: This starts to be a bit tedious, consider moving config into a separate class
def load_config():
    print("Loading config from file...")
    with open(config_path, "r") as f:
        data = json.load(f)
        # General
        inner = data["general"]
        global operation_mode
        operation_mode = inner["mode"]
        global ssh_local_port_webserver
        ssh_local_port_webserver = inner["port"]
        # Timelapse
        inner = data["timelapse"]
        global timelapse_timeout
        timelapse_timeout = inner["timelapse_timeout"]
        # Object detection
        inner = data["object_detection"]
        global record_video
        record_video = inner["record_video"]
        global capture_still
        capture_still = inner["capture_still"]
        global min_score_thresh
        min_score_thresh = inner["min_score_thresh"]
        global min_width_thres
        min_width_thres = inner["min_width_thres"]        
        global object_detection_targets
        object_detection_targets = inner["targets"]
        # Video recording
        inner = data["recording"]
        global rec_format
        rec_format = inner["format"]
        global rec_fps
        rec_fps = inner["fps"]
        global rec_resolution
        rec_resolution = (inner["resolution"]["width"], inner["resolution"]["height"])
        # Photo capturing
        inner = data["capture"]
        global cap_format
        cap_format = inner["format"]
        global cap_resolution
        cap_resolution = (inner["resolution"]["width"], inner["resolution"]["height"])
        # Web MJPEG stream
        inner = data["stream"]
        global stream_bitrate
        stream_bitrate = inner["bitrate"]
        global stream_fps
        stream_fps = inner["fps"]
        global stream_resolution
        stream_resolution = (inner["resolution"]["width"], inner["resolution"]["height"])

# Save new config to JSON file
def save_config(new_config):
    print("Saving new config to file...")
    json_data = json.loads(new_config)
    with open(config_path, "w") as f:
        f.write(json.dumps(json_data, indent=4))

def start_IR_loop(callback_front, callback_back):
    def inner():
        global IR_timestamp
        while True:
            sleep(1)
            now = monotonic()
            if now > IR_timestamp + IR_time_threshold:
                if IR_front.get_value():
                    print("Front side PIR triggered...")
                    IR_timestamp = now
                    callback_front()
                elif IR_back.get_value():
                    print("Back side PIR triggered...")
                    IR_timestamp = now
                    callback_back()
    global IR_loop_running
    if not IR_loop_running:
        IR_loop_running = True
        thread_IR = threading.Thread(target=inner)
        thread_IR.start()

def start_timelapse():
    def inner():
        global timelapse_timeout
        print("Timelapse: Starting with timeout of %d seconds..." % timelapse_timeout)
        while True:
            sleep(timelapse_timeout)
            print("Timelapse: Taking a photo")
            take_photo(project_path + "/footage/timelapse/" + get_string_time())
    global timelapse_running
    if not timelapse_running:
        timelapse_running = True
        thread_timelapse = threading.Thread(target=inner)
        thread_timelapse.start()

def get_string_time():
    return strftime('%b-%d-%Y_%H:%M:%S')

class StreamingOutput(object):
    def __init__(self):
        global rec_fps
        global stream_fps
        self.drop_frame_increment = stream_fps / rec_fps
        self.drop_counter = 0
        self.frame = None
        self.buffer = io.BytesIO()
        self.condition = threading.Condition()

    def write(self, buf):
        if buf.startswith(b'\xff\xd8'):
            self.drop_counter += self.drop_frame_increment
            if self.drop_counter < 1:
                return len(buf) # Fake the succesfull write, but do not actually write anything
            self.drop_counter -= 1 
            # New frame, copy the existing buffer's content and notify all
            # clients it's available
            self.buffer.truncate()
            with self.condition:
                self.frame = self.buffer.getvalue()
                self.condition.notify_all()
            self.buffer.seek(0)
        return self.buffer.write(buf)

# Class implementing replies to the HTTP requests (GET/POST) 
class StreamingHandler(server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(301)
            self.send_header('Location', '/index.html')
            self.end_headers()
        elif self.path == '/index.html':
            content = PAGE.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', len(content))
            self.end_headers()
            self.wfile.write(content)
        elif self.path == '/stream.mjpg':
            self.send_response(200)
            self.send_header('Age', 0)
            self.send_header('Cache-Control', 'no-cache, private')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=FRAME')
            self.end_headers()
            try:
                while stream_enabled:
                    with g_output.condition:
                        g_output.condition.wait()
                        frame = g_output.frame
                    self.wfile.write(b'--FRAME\r\n')
                    self.send_header('Content-Type', 'image/jpeg')
                    self.send_header('Content-Length', len(frame))
                    self.end_headers()
                    self.wfile.write(frame)
                    self.wfile.write(b'\r\n')
                print("Shutting down server...")
                global webserver_restart
                webserver_restart = True
                g_server.shutdown()
                g_server.server_close()
            except Exception as e:
                logging.warning(
                    'Removed streaming client %s: %s',
                    self.client_address, str(e))
        elif self.path.endswith(('.png', '.js', '.css')):
            f = open(self.path, 'rb')
            self.send_response(200)
            if self.path.endswith('.png'):
                self.send_header('Content-type', 'image/png')
            elif self.path.endswith('.js'):
                self.send_header('Content-type', 'text/javascript')
            elif self.path.endswith('.js'):
                self.send_header('Content-type', 'text/css')
            self.end_headers()
            self.wfile.write(f.read())
            f.close()
        elif self.path.endswith('favicon.ico'):
            f = open(project_path + "/webserver/favicon.ico", 'rb')
            self.send_response(200)
            self.send_header('Content-type', 'image/ico')
            self.end_headers()
            self.wfile.write(f.read())
        else:
            self.send_error(404)
            self.end_headers()

    def do_POST(self):      
        global stream_enabled
        self.send_response(200)
        self.end_headers()
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        data = post_data.decode("utf-8").strip()
        print("POST: path:", self.path, "data:", data)
        try:
            response_text = "ok"
            if self.path.endswith("sendRot"):
                stepper.set_command(data)
            elif self.path.endswith("sendConf"):
                save_config(data)
            elif self.path.endswith("sendConfApply"):
                save_config(data)
                stream_enabled = False
            else:
                response_text = "Unknown request: %s" % self.path
            self.wfile.write(response_text.encode())
        except Exception as e:
            print(repr(e))
            self.wfile.write(str(e).encode())

class StreamingServer(socketserver.ThreadingMixIn, server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True

# Capture a still frame
def take_photo(path=project_path + "/test"):
    if g_camera:
        if cap_format == "jpeg":
            file_extension = ".jpg"
        else:
            file_extension = "." + cap_format
        g_camera.capture(path + file_extension, format=cap_format, resize=cap_resolution, splitter_port=cap_splitter_port)

# Start recording a video
def start_rec(path=project_path + "/test"):
    if g_camera:
        global is_recording
        if not is_recording:
            file_extension = ".mp4"
            g_camera.start_recording(path + file_extension, format=rec_format, splitter_port=rec_splitter_port)
            is_recording = True

def stop_rec():
    if g_camera:
        global is_recording
        g_camera.stop_recording(splitter_port=rec_splitter_port)
        is_recording = False

def record_until_idle(path=project_path + "/test", timeout=30):
    def inner():
        global is_recording
        while True:
            sleep(1)
            now = monotonic()
            if now > record_until_idle_timestamp + timeout:
                stop_rec()
                print("Record until idle: %d seconds of idle state reached. Recording stopped." % timeout)
                break
            if not is_recording:
                break

    global record_until_idle_timestamp
    record_until_idle_timestamp = monotonic()
    global is_recording
    if not is_recording:
        print("Record until idle: Start recording with an idle timeout of %d seconds..." % timeout)
        start_rec(path)
        record_until_idle_thread = threading.Thread(target=inner)
        record_until_idle_thread.start()
    else:
        print("Record until idle: Timestamp updated...")

def start_webserver():
    print("Starting webserver...")
    global g_camera
    global g_output
    global g_server
    global stream_enabled
    with picamera.PiCamera(resolution= "%dx%d" % (rec_resolution[0], rec_resolution[1]), framerate=rec_fps) as camera:
        g_camera = camera
        g_output = StreamingOutput()
        camera.rotation = rec_rotation
        # Webserver stream
        camera.start_recording(g_output, format='mjpeg', quality=40, bitrate=stream_bitrate, resize=stream_resolution, splitter_port=stream_splitter_port)
        try:
            address = ('', ssh_local_port_webserver)
            g_server = StreamingServer(address, StreamingHandler)
            print("Server started at port %d" % ssh_local_port_webserver)
            g_server.serve_forever()
        finally:
            print("Finishing...")
            stream_enabled = False
            g_server.shutdown()
            g_server.server_close()
            camera.stop_recording(splitter_port=stream_splitter_port)
            try:
                pass
                #camera.stop_recording(splitter_port=rec_splitter_port)
            except picamera.exc.PiCameraNotRecording:
                pass

def init_webserver():
    load_index_page()
    start_webserver()

def init_object_detection():
    create_ssh_tunnels() # Create two reverse SSH tunnels (will fail and do nothing if they already exist)
    # In case the previous backend task was just killed:
    #   Wait for a while to let the change (the broken ssh connection) propagate to the other end
    sleep(3)
    run_backend(backend_command)




start_stepper()  # Stepper does not need to be restarted with webserver 
start_receiver() # Receiver does not need to be restarted with webserver

while webserver_restart:
    g_camera = None
    g_output = None
    g_server = None
    stream_enabled = True
    webserver_restart = False

    load_config()
    kill_backend()

    print("Mode of operation:", operation_mode)

    if operation_mode == "object_detection_without_PIR":
        init_object_detection()
    elif operation_mode == "object_detection_with_PIR":
        init_object_detection()
        def fn_IR_front():
            pass
        def fn_IR_back():
            if not is_recording: # Do not interrupt recording by rotating based on PIR input
                stepper.set_command("R %d" % (int(180 * 1.49))) # Rotate 180 degrees
        start_IR_loop(fn_IR_front, fn_IR_back)
    elif operation_mode == "PIR_triggered_only":
        def fn_IR_front():
            record_until_idle(project_path + "/footage/videos/" + get_string_time())
        def fn_IR_back():
            stepper.set_command("R %d" % (int(180 * 1.49))) # Rotate 180 degrees
            record_until_idle(project_path + "/footage/videos/" + get_string_time())
        start_IR_loop(fn_IR_front, fn_IR_back)
    elif operation_mode == "timelapse":
        start_timelapse()

    init_webserver()