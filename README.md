
# RPi camera with AI object detection
The project in this repository is implementing a Raspberry Pi Zero W based device with a camera and a stepper motor, which can rotate around its vertical axis. This rotation can be initiated either from its webpage interface or based on a object detection result. [**Tensorflow**](https://www.tensorflow.org/) was used as an AI framework for the object detection itself.
The RPi Zero sends image data to a remote server which is capable of running a tensorflow session. The implementation of the backend part (including Tensorflow) is not *yet* part of this repository.

## Demo (YouTube video)
<div align="left">
      <a href="https://www.youtube.com/watch?v=meXHgsdEl6E">
         <img src="https://img.youtube.com/vi/meXHgsdEl6E/0.jpg" style="width:100%;">
      </a>
</div>

## Directory structure
- [**footage/**](https://github.com/10ondr/AI-Camera/tree/master/footage) - (empty directory tree) Only for a reference on what the output directory structure looks like.
- [**webserver/**](https://github.com/10ondr/AI-Camera/tree/master/webserver) - Client side (RPi) implementation.
- [**webserver/webserver.py**](https://github.com/10ondr/AI-Camera/blob/master/webserver/webserver.py) - Webserver and all client side logic of the application (possibly the only script that needs to run).
- [**webserver/index.html**](https://github.com/10ondr/AI-Camera/blob/master/webserver/index.html) - The entry point webpage served by the webserver. Includes stream preview, manual rotation controls and configuration tab.

## Requirements
### Hardware
- Any Raspberry Pi compatible device with CSI connector for the RPi camera module and wifi connectivity. I used the [Raspberry Pi Zero W](https://www.raspberrypi.org/products/raspberry-pi-zero-w/).
-  Raspberry Pi compatible camera. I used [this](https://www.aliexpress.com/item/33062418914.html?spm=a2g0s.9042311.0.0.2d8c4c4ddX9A6V) cheap clone.
- Stepper motor. I used [this](https://components101.com/motors/28byj-48-stepper-motor) one.

### Software
- Raspberry OS
- sshpass (`apt-get install sshpass`)
- picamera (`python3 -m pip install picamera`)

## How it works
  <img src="https://i.ibb.co/RG8jTsx/r.png">

 There are two parts of this project - backend and client side. Backend is a computer, server or even a powerful smartphone that has installed the Tensorflow framework and is connected to the desired network (the internet in my case). A suitable convolutional neural network (CNN) model needs to be chosen. I used a simple one which is capable of recognizing upto 90 different objects (people, animals, furniture, cars,...).
The client side creates two reverse SSH tunnels, one for image data being sent to the backend and the second one for the results of the object detection back to client. Based on the result, the stepper motor can turn to keep the camera focused on the desired object even if it moves.

## Implementation
### Backend
- Tensorflow, object detection and SSH communication handling in Python

### Client
- Python webserver
- [jsoneditor](https://github.com/json-editor/json-editor) and [CSS Spectre](https://picturepan2.github.io/spectre/) used for the configuration tab.

## Configuration
In the index.html webpage there is a config tab which allows for various configurations of the device. Most of it should be self explanatory.
Different object detection targets can be selected - for example if the camera should only lock its focus on humans or perhaps animals, cars,... Multiple target types simultaneously are supported with the respect to their priority (order in the list).


## Aditional features
- **PIR** - There are two PIR sensors (one on each side) to rotate the device 180 degrees if movement is detected in the otherwise blind area of the camera.
- **Timelapse** - The device in the timelapse mode will ignore any motion and will simply create a timelapse sequence.
